# Third-party components and their licenses

This repository ships scripts, configuration and documentation. The one binary we
publish is the patched Vulkan driver described below, and it comes with its source.
Each component keeps its own license and its own copyright holder.

## What this repository contains

Everything written in this repository, including the `fsr-xmx` command, the
`game/` and `driver/` scripts, the tools and the documentation, is under the GNU
Affero General Public License version 3 or later, in [LICENSE](LICENSE). If you
distribute a modified version, or run one as a network service, you have to make
its source available under the same license.

## Software the installers use

| Component | Where it comes from | License | Bundled here |
|---|---|---|---|
| `xess-xmx-linux` | Upstream project, pinned at `f06dc39` | MIT, copyright HHHHanasak1. MIT code can be combined with AGPL code, and the combined work stays AGPL | Its patches are applied to build our driver, not copied into this repository |
| Mesa 3D (the patched Vulkan driver) | mesa3d.org plus the patches in [patches/](patches/) | MIT | We publish the compiled library; see the section below |
| vkd3d-proton | Valve's fork of vkd3d | LGPL-2.1 | No |
| `igdext64.dll` | Intel graphics driver components, taken from the upstream package | Intel's own terms, see the upstream package | No |
| nitec's FSR 4 XMX mod | NexusMods, author nitec | No public license that allows redistribution | No. The user supplies the file and the installer checks its sha256 |
| AMD FidelityFX DLL (`fsr-original.dll`) | Extracted from a game or an SDK copy that ships FSR 4.1.2 | AMD's own terms | No. The user supplies the file |
| OptiScaler | github.com/OptiScalers/OptiScaler | Its own license, see that repository | No. The installer expects the official release files |
| ANR frame generation add-on | github.com/apex-compute/ANR | Its own license, see that repository | No |

Because the mod and the AMD DLL are not redistributable, `game/install.sh` refuses
to run until the user puts them in the game folder. [game/PUT-THE-FILES-HERE.txt](game/PUT-THE-FILES-HERE.txt)
lists the exact sizes and sha256 values, so a wrong version stops before anything is
copied.

## The driver binary we publish

The driver library we ship is built from Mesa 26.3 with the upstream
`xess-xmx-linux` patches and our own patch on top, `patches/0001-anv-cmk3-explicit-mapping.patch`.
That patch edits files that carry the upstream MIT notice, and it keeps that notice
in every hunk it touches.

Because our own additions are under the AGPL, publishing the binary comes with an
obligation: whoever receives it must be able to get the exact source. The release
therefore points at this repository, the pinned upstream revision and the Mesa
version, and [docs/installer-design.md](docs/installer-design.md) records the build
steps. The release archive also carries `LICENSE` and this file, so the Mesa and
upstream MIT notices travel with the binary.

## Game footage

The comparison videos in [media/quality-cp77](media/quality-cp77) are recordings of
Cyberpunk 2077, and the game, its artwork and its name belong to CD Projekt Red. They
are here to compare image quality and for no other purpose.

## What this repository does not grant

Nothing in this repository gives you a license to redistribute nitec's mod, AMD's
DLL, Intel's DLL or OptiScaler. If you want to ship them inside your own package,
ask their authors first.
