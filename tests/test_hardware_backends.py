import json
import os
import runpy
import subprocess
import tempfile
import unittest


MODULE = runpy.run_path("jellyfin-ffmpeg-shim")


class HardwareBackendTests(unittest.TestCase):
    def classify(self, *argv):
        return MODULE["classify_command"](list(argv))

    def test_intel_qsv_is_detected_from_encoder(self):
        info = self.classify("-c:v", "hevc_qsv", "out.mkv")
        self.assertEqual(info["hardware_backend"]["id"], "intel_qsv")
        self.assertTrue(info["is_hw_pipeline"])
        self.assertEqual(info["hardware_pipeline_variant"], "unrecognized")

    def test_native_vaapi_is_vendor_neutral_and_not_implemented(self):
        info = self.classify(
            "-hwaccel", "vaapi", "-vf", "scale_vaapi=format=p010",
            "-c:v", "hevc_vaapi", "out.mkv",
        )
        self.assertEqual(info["hardware_backend"]["id"], "vaapi")
        self.assertEqual(info["hardware_backend"]["implemented_modes"], [])

    def test_nvidia_nvenc_is_detected_without_intel_assumptions(self):
        info = self.classify(
            "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
            "-c:v", "hevc_nvenc", "out.mkv",
        )
        self.assertEqual(info["hardware_backend"]["id"], "nvidia_cuda")

    def test_amd_amf_is_detected(self):
        info = self.classify("-c:v", "hevc_amf", "out.mkv")
        self.assertEqual(info["hardware_backend"]["id"], "amd_amf")

    def test_vulkan_video_is_detected(self):
        info = self.classify("-c:v", "hevc_vulkan", "out.mkv")
        self.assertEqual(info["hardware_backend"]["id"], "vulkan")

    def test_software_x265_remains_software_with_initialized_devices(self):
        info = self.classify(
            "-init_hw_device", "vaapi=va:", "-c:v", "libx265", "out.mkv",
        )
        self.assertEqual(info["hardware_backend"]["id"], "software")
        self.assertFalse(info["is_hw_pipeline"])

    def test_disabled_client_filtering_allows_safe_rewrite_without_api(self):
        old_value = MODULE["ENABLE_CLIENT_ALLOW_DENY"]
        MODULE["ENABLE_CLIENT_ALLOW_DENY"] = False
        try:
            report = {"blocking_client_decision": []}
            decision = MODULE["blocking_client_decision"]([], report)
        finally:
            MODULE["ENABLE_CLIENT_ALLOW_DENY"] = old_value
        self.assertTrue(decision["allow_hdr_to_hdr"])
        self.assertEqual(decision["confidence"], "not_required")
        self.assertIn("without Jellyfin API lookup", report["blocking_client_decision"][0])

    def test_config_allows_missing_api_key_when_client_filtering_is_disabled(self):
        with open("shim.json.example", encoding="utf-8") as source:
            config = json.load(source)
        config["shim"]["enable_client_allow_deny"] = False
        config["jellyfin"]["api_key"] = ""
        config["shim"]["enable_opencl_subtitle_compositor"] = False
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as handle:
            json.dump(config, handle)
            handle.flush()
            env = os.environ.copy()
            env["JELLYFIN_SHIM_CONFIG"] = handle.name
            completed = subprocess.run(
                ["python3", "jellyfin-ffmpeg-shim", "--check-config"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        state = json.loads(completed.stdout)
        self.assertIsNone(state["config_load_error"])
        self.assertEqual(state["kill_switch"], 0)
        self.assertFalse(state["opencl_subtitle_compositor"])

    def test_unimplemented_backend_fails_closed_without_mutation(self):
        argv = [
            "-hwaccel", "cuda", "-vf",
            "tonemap_cuda=tonemap=bt2390:format=yuv420p",
            "-c:v", "hevc_nvenc", "out.mkv",
        ]
        info = MODULE["classify_command"](argv)
        report = {"hdr_to_hdr": []}
        rewritten = MODULE["rewrite_hardware_backend"](
            argv,
            report,
            info,
            {"conversion_mode": "preserve_hdr10_base"},
            {"allow_hdr_to_hdr": True},
        )
        self.assertEqual(rewritten, argv)
        self.assertIn(
            "no HDR rewrite handler is implemented for NVIDIA CUDA/NVENC",
            "\n".join(report["hdr_to_hdr"]),
        )

    def test_existing_intel_hdr_graph_still_rewrites(self):
        vf = (
            "setparams=color_primaries=bt2020:color_trc=smpte2084:"
            "colorspace=bt2020nc,procamp_vaapi=b=16,"
            "tonemap_vaapi=format=nv12:p=bt709:t=bt709:m=bt709,"
            "hwmap=derive_device=qsv,format=qsv"
        )
        argv = [
            "-hwaccel_output_format", "vaapi", "-vf", vf,
            "-c:v", "hevc_qsv", "-profile:v", "main", "out.mkv",
        ]
        info = MODULE["classify_command"](argv)
        self.assertTrue(info["is_supported_vaapi_qsv_pipeline"])
        self.assertEqual(info["hardware_pipeline_variant"], "vaapi_qsv_hdr10")
        report = {"hdr_to_hdr": []}
        rewritten = MODULE["rewrite_hardware_backend"](
            argv,
            report,
            info,
            {"conversion_mode": "preserve_hdr10_base"},
            {"allow_hdr_to_hdr": True},
        )
        self.assertNotEqual(rewritten, argv)
        new_vf = rewritten[rewritten.index("-vf") + 1]
        self.assertIn("scale_vaapi=format=p010", new_vf)
        self.assertNotIn("tonemap_vaapi", new_vf)

    def test_existing_intel_profile5_graph_still_rewrites(self):
        vf = (
            "setparams=color_primaries=bt2020:color_trc=smpte2084:"
            "colorspace=bt2020nc,hwmap=derive_device=opencl:mode=read,"
            "tonemap_opencl=format=nv12:p=bt709:t=bt709:m=bt709:"
            "tonemap=bt2390:peak=100:desat=0,"
            "hwmap=derive_device=qsv:mode=write:reverse=1:extra_hw_frames=16,"
            "format=qsv"
        )
        argv = ["-vf", vf, "-c:v", "hevc_qsv", "out.mkv"]
        info = MODULE["classify_command"](argv)
        self.assertEqual(
            info["hardware_pipeline_variant"], "vaapi_opencl_qsv_dovi"
        )
        report = {"hdr_to_hdr": []}
        rewritten = MODULE["rewrite_hardware_backend"](
            argv,
            report,
            info,
            {"conversion_mode": "dovi_profile5_to_hdr10"},
            {"allow_hdr_to_hdr": True},
        )
        new_vf = rewritten[rewritten.index("-vf") + 1]
        self.assertIn("tonemap_opencl=format=p010", new_vf)
        self.assertIn("apply_dovi=true", new_vf)
        self.assertNotIn("p=bt709", new_vf)

    def test_vaapi_rewrite_preserves_jellyfin_frame_pool_size(self):
        original = (
            "setparams=color_primaries=bt2020:color_trc=smpte2084:"
            "colorspace=bt2020nc,procamp_vaapi=b=16,"
            "tonemap_vaapi=format=nv12:p=bt709:t=bt709:m=bt709:"
            "extra_hw_frames=23,hwmap=derive_device=qsv,format=qsv"
        )
        rewritten, message = MODULE["replace_vaapi_tonemap_with_hdr"](original)
        self.assertNotIn("BAIL:", message)
        self.assertIn("extra_hw_frames=23", rewritten)
        self.assertNotIn("extra_hw_frames=32", rewritten)

    def test_subtitle_rewrite_preserves_jellyfin_upload_pool_size(self):
        graph = (
            "[0:7]scale,scale=1920:1080:fast_bilinear,format=bgra,"
            "hwupload=derive_device=qsv:extra_hw_frames=27[sub];"
            "[0:0]setparams=color_primaries=bt2020:color_trc=smpte2084:"
            "colorspace=bt2020nc,procamp_vaapi=b=16,"
            "tonemap_vaapi=format=nv12:p=bt709:t=bt709:m=bt709:"
            "extra_hw_frames=19,hwmap=derive_device=qsv,format=qsv[main];"
            "[main][sub]overlay_qsv=eof_action=pass:repeatlast=0:"
            "w=3840:h=2160"
        )
        rewritten, message = MODULE["rewrite_intel_qsv_subtitle_graph"](graph)
        self.assertNotIn("BAIL:", message)
        self.assertIn("hwupload=derive_device=qsv:extra_hw_frames=27", rewritten)
        self.assertIn("scale_vaapi=format=p010", rewritten)
        self.assertIn("extra_hw_frames=19", rewritten)

    def test_subtitle_rewrite_uses_opencl_compositor_when_available(self):
        graph = (
            "[0:7]scale,scale=1920:1080:fast_bilinear,format=bgra,"
            "hwupload=derive_device=qsv:extra_hw_frames=27[sub];"
            "[0:0]setparams=color_primaries=bt2020:color_trc=smpte2084:"
            "colorspace=bt2020nc,procamp_vaapi=b=16,"
            "tonemap_vaapi=format=nv12:p=bt709:t=bt709:m=bt709:"
            "extra_hw_frames=19,hwmap=derive_device=qsv,format=qsv[main];"
            "[main][sub]overlay_qsv=eof_action=pass:repeatlast=0:"
            "w=3840:h=2160"
        )
        rewritten, message = MODULE["rewrite_intel_qsv_subtitle_graph"](
            graph, use_opencl_compositor=True
        )
        self.assertNotIn("BAIL:", message)
        self.assertIn("overlay_p010_bgra_opencl=", rewritten)
        self.assertIn("hwmap=derive_device=opencl:mode=read+write", rewritten)
        self.assertIn("hwmap=derive_device=vaapi:mode=read+write,format=vaapi", rewritten)
        self.assertIn("hwmap=derive_device=qsv,format=qsv", rewritten)
        self.assertNotIn("hwdownload", rewritten)
        self.assertIn("extra_hw_frames=27", rewritten)


if __name__ == "__main__":
    unittest.main()
