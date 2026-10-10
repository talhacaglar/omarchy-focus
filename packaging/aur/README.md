# AUR packaging

`PKGBUILD`, `omarchy-focus.install` and `.SRCINFO` for https://aur.archlinux.org/packages/omarchy-focus.

Release steps:

1. Tag `vX.Y.Z` and push the tag.
2. Bump `pkgver`, reset `pkgrel=1`, update `sha256sums` (`updpkgsums`).
3. `makepkg -sfr` to build and run the tests.
4. `makepkg --printsrcinfo > .SRCINFO`
5. Copy the three files into the AUR git clone (`ssh://aur@aur.archlinux.org/omarchy-focus.git`), commit, push.
