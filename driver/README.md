# The driver step

Once per machine, needs root. It writes to `/usr`, `/opt` and `/etc`, so it
changes the machine for every account there.

The download carries the bundle folder next to the script. Run it there:

```bash
sudo ./install.sh
```

Log out and back in afterwards, or use the `export` line the script prints.
Then do the game step, a separate download with its own README.

## What it writes

The patched Mesa ANV driver in `/usr/lib/fsr-xmx/`, an ICD file next to Mesa's
own in `/usr/share/vulkan/icd.d/`, the two Windows stand-ins in `/opt/fsr-xmx/`,
and `/etc/environment.d/fsr-xmx.conf` with `VK_DRIVER_FILES`, the kernel folder,
the compiler helper and the Wine DLL overrides. The install checks every file
against `SHA256SUMS` first. Mesa's own ICD file stays: only `VK_DRIVER_FILES`
selects the new one, so unsetting that variable goes back to Mesa. With
snapper it takes a snapshot of the root config and prints the number.

## Undo

Run `sudo ./uninstall.sh`. It removes exactly the paths in
`/opt/fsr-xmx/created.tsv` and refuses when one changed since the install.
Undo each game first. Log out and back in afterwards.
