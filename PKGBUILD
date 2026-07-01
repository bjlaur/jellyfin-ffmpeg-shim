pkgname=jellyfin-ffmpeg-shim
pkgver=0.1.0
pkgrel=10
pkgdesc='Jellyfin FFmpeg shim for selective HDR-to-HDR transcoding'
arch=('any')
url=''
license=('custom:unlicensed')
depends=('python' 'jellyfin-ffmpeg')
install='jellyfin-ffmpeg-shim.install'
backup=('etc/jellyfin/shim.json')
source=(
  'jellyfin-ffmpeg-shim'
  'shim.json.example'
)
sha256sums=(
  'SKIP'
  'SKIP'
)

package() {
  install -Dm755 jellyfin-ffmpeg-shim \
    "$pkgdir/usr/bin/jellyfin-ffmpeg-shim"
  install -Dm640 shim.json.example \
    "$pkgdir/etc/jellyfin/shim.json"
}
