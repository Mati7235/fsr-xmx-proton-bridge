# The driver step

Once per machine, needs root. It writes to `/usr`, `/opt` and `/etc`, so it changes
the machine for every account there.

1. Download the driver bundle, the folder with `MANIFEST`, `SHA256SUMS`, `icd/`,
   `lib/`, `igdext64.dll`, `cabinet.dll` and `tools/`.
2. Put it in `bundle/`, or pass its path: `sudo ./install.sh --from <folder>`.
3. Log out and back in, or use the `export` line the script prints.
4. Do the game step, see `game/README.md`.

## What it writes

- `/usr/lib/fsr-xmx/libvulkan_intel.so`, the patched Mesa ANV driver.
- `/usr/share/vulkan/icd.d/fsr-xmx-intel_icd.json`, a Vulkan driver description
  that points at that library.
- `/opt/fsr-xmx/igdext64.dll` and `/opt/fsr-xmx/cabinet.dll`, the two Windows
  stand-ins, kept machine-wide for an account that copies them by hand.
- `/etc/environment.d/fsr-xmx.conf` with `VK_DRIVER_FILES` pointing at the new ICD,
  the kernel folder and compiler helper, and the Wine DLL overrides. No `FSR4_XMX_*`
  model variables: those belong to one game and `fsr-xmx run` sets them.

The install checks every file in the bundle against `SHA256SUMS` before writing
anything. When `snapper` is installed it takes a snapshot of the root config first
and prints the number; it never deletes a snapshot.

Mesa's own ICD file stays where it is. The new file is an addition, and only
`VK_DRIVER_FILES` selects it, so you can go back to Mesa by unsetting that variable.

`/etc/environment.d` is read when a login session starts, so the settings reach new
sessions only. The script prints the one-line `export` for the session you are in.

## Undo

`sudo ./uninstall.sh` removes exactly the paths listed in
`/opt/fsr-xmx/created.tsv`, the manifest from install time, and refuses when one of
them changed since. Undo each game first with `game/uninstall.sh`: the per-user part
refuses while a game is still set up. It is also the rollback if Vulkan applications
stop starting. Log out and back in afterwards.
