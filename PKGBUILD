pkgname=jellyfin-ffmpeg-shim
pkgver=0.1.0
pkgrel=2
pkgdesc='Jellyfin FFmpeg shim for selective HDR-to-HDR transcoding'
arch=('any')
url='https://github.com/bjlaur/jellyfin-ffmpeg-shim'
license=('MIT')
depends=('python' 'jellyfin-ffmpeg')
install='jellyfin-ffmpeg-shim.install'
backup=('etc/jellyfin/shim.json')
source=(
  'jellyfin-ffmpeg-shim'
  'shim.json.example'
  'README.md'
  'LICENSE'
)
sha256sums=(
  'SKIP'
  'SKIP'
  'SKIP'
  'SKIP'
)

package() {
  install -Dm755 jellyfin-ffmpeg-shim \
    "$pkgdir/usr/local/bin/jellyfin-ffmpeg-shim"
  ln -s /usr/lib/jellyfin-ffmpeg/ffprobe \
    "$pkgdir/usr/local/bin/ffprobe"
  install -Dm640 shim.json.example \
    "$pkgdir/etc/jellyfin/shim.json"
  install -Dm644 README.md \
    "$pkgdir/usr/share/doc/$pkgname/README.md"
  install -Dm644 LICENSE \
    "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
