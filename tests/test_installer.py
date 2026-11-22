#!/usr/bin/env python3
"""Tests for installer/fsr-xmx against throwaway fake trees (no real Steam)."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "installer" / "fsr-xmx"
COMMON = REPO / "installer" / "lib" / "common.sh"
REAL_PROFILE = REPO / "installer" / "profiles" / "cyberpunk2077.conf"

INI_ORIGINAL = (
    b"; test ini\r\n"
    b"\r\n"
    b"[Upscalers]\r\n"
    b"\r\n"
    b"; Select Upscaler for Dx12 games\r\n"
    b"Dx12Upscaler = auto\r\n"
    b"\r\n"
    b"[FrameGen]\r\n"
    b"\r\n"
    b"Enabled = false\r\n"
    b"\r\n"
    b"FGInput = Upscaler\r\n"
    b"\r\n"
    b"FGOutput = auto\r\n"
    b"\r\n"
    b"FGNvngxReplacement = auto\r\n"
    b"\r\n"
    b"DisableHudless = auto\r\n"
    b"\r\n"
    b"[Spoofing]\r\n"
    b"\r\n"
    b"SpoofedVendorId = auto\r\n"
    b"\r\n"
    b"SpoofedDeviceId = 0x2684\r\n"
    b"\r\n"
    b"Dxgi = true\r\n"
    b"\r\n"
    b"[FSR]\r\n"
    b"\r\n"
    b"Fsr4GpuSupport = auto\r\n"
    b"\r\n"
    b"Fsr4Preset = auto\r\n"
    b"\r\n"
    b"Fsr4Model = auto\r\n"
)

EXPECTED_XEFG = (
    INI_ORIGINAL
    .replace(b"Dx12Upscaler = auto", b"Dx12Upscaler = ffx")
    .replace(b"Enabled = false", b"Enabled = true")
    .replace(b"FGOutput = auto", b"FGOutput = XeFG")
    .replace(b"SpoofedVendorId = auto", b"SpoofedVendorId = 0x8086")
    .replace(b"SpoofedDeviceId = 0x2684", b"SpoofedDeviceId = 0xE20B")
    .replace(b"Dxgi = true", b"Dxgi = false")
)

EXPECTED_ANR = (
    EXPECTED_XEFG
    .replace(b"FGInput = Upscaler", b"FGInput = nvngxfg")
    .replace(b"FGNvngxReplacement = auto",
             b"FGNvngxReplacement = Apex Neural Rendering FG")
    .replace(b"DisableHudless = auto", b"DisableHudless = false")
)

VKD3D_OFF = ("VK_EXT_descriptor_buffer,VK_EXT_descriptor_heap,"
             "VK_KHR_present_wait2")


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.tmp = Path(self.tmpdir.name)
        self.home = self.tmp / "home"
        self.steam = self.tmp / "steam"
        self.game = self.tmp / "game" / "bin" / "x64"
        self.profiles = self.tmp / "profiles"
        self.bundle = self.tmp / "bundle"
        self.sysfs = self.tmp / "sys"
        self.libvulkan = self.tmp / "lib" / "libvulkan.so.1"
        self.data_dir = self.home / "data"
        self.cache_dir = self.home / "cache"
        self.root = self.data_dir / "fsr-xmx"
        self.ini = self.game / "OptiScaler.ini"
        for path in (self.home, self.steam / "compatibilitytools.d",
                     self.sysfs / "bus" / "pci" / "drivers" / "xe",
                     self.libvulkan.parent, self.profiles):
            path.mkdir(parents=True, exist_ok=True)
        self.libvulkan.write_bytes(b"loader\n")
        device = self.sysfs / "class" / "drm" / "card0" / "device"
        device.mkdir(parents=True)
        (device / "vendor").write_text("0x8086\n")
        (device / "device").write_text("0xe20b\n")
        (device / "driver").symlink_to(self.sysfs / "bus" / "pci" / "drivers" / "xe")
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.home),
            "LANG": "C.UTF-8",
            "TMPDIR": str(self.tmp / "tmp"),
            "XDG_DATA_HOME": str(self.data_dir),
            "XDG_CACHE_HOME": str(self.cache_dir),
            "FSR_XMX_PROFILES": str(self.profiles),
            "FSR_XMX_STEAM": str(self.steam),
            "FSR_XMX_SYSFS": str(self.sysfs),
            "FSR_XMX_VULKAN_LOADER": str(self.libvulkan),
        }
        (self.tmp / "tmp").mkdir()
        self.make_game()
        self.make_bundle()
        self.make_profile()

    def run_cli(self, *args, extra_env=None, check=False, cwd=None):
        env = dict(self.env)
        if extra_env:
            env.update(extra_env)
        result = subprocess.run([str(SCRIPT), *args], env=env, text=True,
                                capture_output=True, cwd=str(cwd or self.tmp))
        if check and result.returncode != 0:
            self.fail("failed %s: %s\n%s" % (args, result.stdout, result.stderr))
        return result

    def make_game(self):
        self.game.mkdir(parents=True)
        (self.game / "Cyberpunk2077.exe").write_bytes(b"MZ fake exe\n")
        (self.game / "amd_fidelityfx_upscaler_dx12.dll").write_bytes(b"mod xmx 4.1.2\n")
        (self.game / "fsr-original.dll").write_bytes(b"amd fsr 4.1.2\n")
        (self.game / "dxgi.dll").write_bytes(b"optiscaler proxy\n")
        self.ini.write_bytes(INI_ORIGINAL)

    def make_bundle(self):
        files = {
            "MANIFEST": b"VERSION=test-1\nMESA=26.3.1\nVKD3D=2576c0b4\n",
            "icd/intel_icd.json": b'{"file_format_version": "1.0.0"}\n',
            "lib/libvulkan_intel.so": b"fake anv\n",
            "igdext64.dll": b"igdext shim\n",
            "cabinet.dll": b"cabinet shim\n",
            "vkd3d-proton/x86_64-windows/d3d12.dll": b"vkd3d d3d12\n",
            "vkd3d-proton/x86_64-windows/d3d12core.dll": b"vkd3d d3d12core\n",
            "tools/cm-compile.sh": b"#!/bin/sh\nexit 0\n",
        }
        for name, data in files.items():
            path = self.bundle / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        lines = []
        for name in sorted(files):
            lines.append("%s  %s\n" % (self.sha(self.bundle / name), name))
        (self.bundle / "SHA256SUMS").write_text("".join(lines))

    def make_profile(self):
        text = REAL_PROFILE.read_text()
        replacements = {
            "MOD_SHA256": self.sha(self.game / "amd_fidelityfx_upscaler_dx12.dll"),
            "MOD_SIZE": str((self.game / "amd_fidelityfx_upscaler_dx12.dll").stat().st_size),
            "FSR_ORIGINAL_SHA256": self.sha(self.game / "fsr-original.dll"),
            "FSR_ORIGINAL_SIZE": str((self.game / "fsr-original.dll").stat().st_size),
        }
        self.set_profile(**replacements)

    def set_profile(self, **values):
        text = REAL_PROFILE.read_text()
        out = []
        for line in text.splitlines(True):
            key = line.split("=", 1)[0]
            if key in values and "=" in line:
                out.append("%s=%s\n" % (key, values[key]))
            else:
                out.append(line)
        (self.profiles / "cyberpunk2077.conf").write_text("".join(out))

    def make_anr_tree(self):
        anr = self.game / "OptiScaler" / "custom" / "Apex Neural Rendering FG" / "dlssg"
        anr.mkdir(parents=True)
        (anr / "nvngx_dlssg.dll").write_bytes(b"anr dlssg\n")
        (anr / "nr_fg.ini").write_bytes(b"path = auto\n")

    def make_ge_proton(self):
        ge = self.tmp / "ge-proton"
        vkd3d = ge / "files" / "lib" / "wine" / "vkd3d-proton" / "x86_64-windows"
        vkd3d.mkdir(parents=True)
        (ge / "proton").write_text("#!/bin/sh\n")
        (ge / "version").write_text("GE-Proton11-12\n")
        (vkd3d / "d3d12.dll").write_bytes(b"ge stock d3d12\n")
        (vkd3d / "d3d12core.dll").write_bytes(b"ge stock d3d12core\n")
        (ge / "compatibilitytool.vdf").write_text(
            '"compatibilitytool.vdf"\n{\n\t"install"\n\t{\n'
            '\t\t"GE-Proton11-12"\n\t\t{\n'
            '\t\t\t"from_oslist"  "windows"\n'
            '\t\t\t"to_oslist"    "linux"\n'
            '\t\t\t"display_name" "GE-Proton11-12"\n'
            '\t\t\t"installpath"  "."\n'
            "\t\t}\n\t}\n}\n")
        return ge

    @staticmethod
    def sha(path):
        import hashlib
        digest = hashlib.sha256()
        digest.update(Path(path).read_bytes())
        return digest.hexdigest()

    def install_ok(self):
        result = self.run_cli("install", "--from", str(self.bundle), check=True)
        self.assertIn("Copied and verified", result.stdout)

    def enable_ok(self, *extra):
        return self.run_cli("enable", str(self.game), *extra, check=True)

    def backup_dirs(self):
        root = self.game / ".fsr-xmx-backup"
        if not root.is_dir():
            return []
        return sorted(path for path in root.iterdir() if path.is_dir())

    def state_path(self):
        return self.root / "profiles" / "cyberpunk2077" / "state.conf"

    def state_key(self, key):
        for line in self.state_path().read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1]
        return None

    def test_bash_syntax(self):
        for script in (SCRIPT, COMMON):
            result = subprocess.run(["bash", "-n", str(script)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_shellcheck_when_available(self):
        if shutil.which("shellcheck") is None:
            self.skipTest("shellcheck is not installed")
        result = subprocess.run(["shellcheck", "-S", "warning", str(SCRIPT),
                                 str(COMMON)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_doctor_reports_fake_hardware(self):
        result = self.run_cli("doctor")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("OK      Intel GPU detected", result.stdout)
        self.assertIn("OK      Linux kernel driver: xe", result.stdout)
        self.assertIn("OK      Vulkan loader found", result.stdout)
        self.assertIn("MISSING the driver is not installed", result.stdout)
        self.assertIn("install --from", result.stdout)

        self.install_ok()
        result = self.run_cli("doctor", str(self.game))
        self.assertIn("OK      active install: versions/test-1", result.stdout)
        self.assertIn("== Cyberpunk 2077", result.stdout)
        self.assertIn("WARN    this game is not set up", result.stdout)
        self.assertIn("OK      FSR4 XMX mod: checksum correct", result.stdout)

    def test_doctor_warns_flatpak_and_i915(self):
        for path in (self.sysfs / "class" / "drm" / "card0" / "device").iterdir():
            if path.is_symlink():
                path.unlink()
        (self.sysfs / "bus" / "pci" / "drivers" / "i915").mkdir()
        (self.sysfs / "class" / "drm" / "card0" / "device" / "driver").symlink_to(
            self.sysfs / "bus" / "pci" / "drivers" / "i915")
        flatpak = self.home / ".var" / "app" / "com.valvesoftware.Steam"
        flatpak.mkdir(parents=True)
        shutil.rmtree(self.steam)
        result = self.run_cli("doctor")
        self.assertIn("WARN    Linux kernel driver: i915", result.stdout)
        self.assertIn("WARN    you have the Flatpak version of Steam", result.stdout)

    def test_doctor_suggests_the_folder_to_pass(self):
        self.install_ok()
        parent = self.game.parent.parent
        result = self.run_cli("doctor", str(parent))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("That folder is not the game folder", result.stdout)
        self.assertIn("Pass this one instead: %s" % self.game, result.stdout)
        self.assertNotIn("== Cyberpunk 2077", result.stdout)

        result = self.run_cli("doctor", str(self.game / "Cyberpunk2077.exe"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("That is a file, not a folder", result.stdout)
        self.assertIn(str(self.game), result.stdout)

    def test_doctor_missing_steam_is_only_a_warning(self):
        self.install_ok()
        self.enable_ok("--fsr4", "int8")
        shutil.rmtree(self.steam)
        result = self.run_cli("doctor", str(self.game))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WARN    Steam was not found", result.stdout)
        self.assertIn("informational", result.stdout)
        self.assertIn("All good.", result.stdout)

    def test_doctor_reports_a_pending_restore(self):
        self.install_ok()
        self.enable_ok("--fsr4", "int8")
        with open(self.state_path(), "a", encoding="utf-8") as handle:
            handle.write("PENDING_RESTORE=OptiScaler.ini|igdext64.dll\n")
        result = self.run_cli("doctor", str(self.game))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("this game is still modified", result.stdout)
        self.assertIn("OptiScaler.ini", result.stdout)
        self.assertIn("igdext64.dll", result.stdout)
        self.assertIn(" disable ", result.stdout)
        self.assertNotIn("OK      set up by fsr-xmx", result.stdout)
        self.assertNotIn("enable again", result.stdout)

    def test_doctor_not_enabled_does_not_say_all_good(self):
        self.install_ok()
        ge = self.make_ge_proton()
        self.run_cli("install-compat-tool", "--ge-dir", str(ge), check=True)
        result = self.run_cli("doctor", str(self.game))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WARN    this game is not set up", result.stdout)
        self.assertNotIn("All good.", result.stdout)
        self.assertIn("Nothing is enabled for this game yet", result.stdout)
        self.assertIn("enable", result.stdout)

    def test_symlinked_script_finds_its_library(self):
        first = self.tmp / "bin-one"
        second = self.tmp / "bin-two"
        first.mkdir()
        second.mkdir()
        direct = first / "fsr-xmx"
        direct.symlink_to(SCRIPT)
        chained = second / "fsr-xmx"
        chained.symlink_to(direct)
        result = subprocess.run([str(chained), "--help"], env=dict(self.env),
                                text=True, capture_output=True,
                                cwd=str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Usage:", result.stdout)

    def test_hints_do_not_contain_the_script_path(self):
        install = self.run_cli("install")
        self.assertIn("install --from", install.stdout)
        self.assertNotIn(str(SCRIPT), install.stdout + install.stderr)

        self.install_ok()
        self.enable_ok("--fsr4", "int8")
        uninstall = self.run_cli("uninstall")
        self.assertIn("disable", uninstall.stdout)
        self.assertNotIn(str(SCRIPT), uninstall.stdout + uninstall.stderr)

        shutil.rmtree(self.root)
        doctor = self.run_cli("doctor")
        self.assertIn("install --from", doctor.stdout)
        self.assertNotIn(str(SCRIPT), doctor.stdout + doctor.stderr)

    def test_install_rejects_tampered_bundle(self):
        (self.bundle / "igdext64.dll").write_bytes(b"igdext shim TAMPERED\n")
        result = self.run_cli("install", "--from", str(self.bundle))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("doesn't match SHA256SUMS", result.stdout)
        self.assertFalse(self.root.exists())

    def test_install_switches_current_atomically(self):
        self.install_ok()
        current = self.root / "current"
        self.assertTrue(current.is_symlink())
        self.assertEqual(os.readlink(current), "versions/test-1")
        self.assertTrue((current / "icd" / "intel_icd.json").is_file())
        second = self.run_cli("install", "--from", str(self.bundle), check=True)
        self.assertIn("is already installed", second.stdout)

    def test_enable_ini_diff_backups_and_state(self):
        self.install_ok()
        self.enable_ok("--fsr4", "int8")
        self.assertEqual(self.ini.read_bytes(), EXPECTED_XEFG)
        self.assertEqual(self.ini.read_bytes().count(b"\n"),
                         self.ini.read_bytes().count(b"\r\n"))

        backups = self.backup_dirs()
        self.assertEqual(len(backups), 1)
        manifest = (backups[0] / "manifest.tsv").read_text()
        self.assertIn("replaced\tOptiScaler.ini\t", manifest)
        self.assertIn("added\tigdext64.dll", manifest)
        self.assertEqual((backups[0] / "files" / "OptiScaler.ini").read_bytes(),
                         INI_ORIGINAL)
        self.assertEqual((self.game / "igdext64.dll").read_bytes(), b"igdext shim\n")
        self.assertEqual((self.game / "cabinet.dll").read_bytes(), b"cabinet shim\n")

        state = self.root / "profiles" / "cyberpunk2077" / "state.conf"
        self.assertTrue(state.is_file())
        text = state.read_text()
        self.assertIn("FSR4=int8\n", text)
        self.assertIn("FG=xefg\n", text)
        self.assertIn("KEEP_COOPMAT=0\n", text)

        again = self.enable_ok("--fsr4", "int8")
        self.assertIn("was already set correctly", again.stdout)
        self.assertEqual(len(self.backup_dirs()), 1)

    def test_enable_prints_a_pasteable_launch_line(self):
        self.install_ok()
        spaced = self.tmp / "games" / "Cyberpunk 2077" / "bin" / "x64"
        spaced.parent.parent.mkdir(parents=True)
        shutil.move(str(self.game), str(spaced))
        self.game = spaced
        self.ini = spaced / "OptiScaler.ini"
        result = self.enable_ok("--fsr4", "int8")
        lines = [line.strip() for line in result.stdout.splitlines()
                 if "-- %command%" in line]
        self.assertEqual(len(lines), 1, result.stdout)
        line = lines[0]
        self.assertTrue(line.startswith("fsr-xmx ")
                        or line.startswith("<path-to-fsr-xmx> "), line)
        self.assertIn("run --profile cyberpunk2077 -- %command%", line)
        self.assertNotIn(str(SCRIPT.parent), line)
        self.assertNotIn(str(self.tmp), line)
        self.assertIn('doctor "%s"' % spaced, result.stdout)

    def test_enable_placeholder_line_says_to_replace_it(self):
        self.install_ok()
        result = self.enable_ok("--fsr4", "int8")
        self.assertIn("First replace <path-to-fsr-xmx> with the full path to fsr-xmx",
                      result.stdout)
        self.assertNotIn("Paste this line into Steam", result.stdout)

    def test_enable_twice_keeps_a_backup_path_that_exists(self):
        self.install_ok()
        self.enable_ok("--fsr4", "int8")
        first = self.state_key("BACKUP")
        self.assertTrue(first)
        self.assertTrue((self.game / first).is_dir())

        self.enable_ok("--fsr4", "int8")
        second = self.state_key("BACKUP")
        self.assertTrue(second)
        self.assertTrue((self.game / second).is_dir(),
                        "state points at a backup that no longer exists")

        self.run_cli("disable", str(self.game), check=True)
        self.assertEqual(self.ini.read_bytes(), INI_ORIGINAL)
        self.assertFalse((self.game / "igdext64.dll").exists())

    def test_enable_rejects_unknown_mod(self):
        self.install_ok()
        (self.game / "amd_fidelityfx_upscaler_dx12.dll").write_bytes(b"otro mod\n")
        result = self.run_cli("enable", str(self.game), "--fsr4", "int8")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FSR4 XMX 4.1.2 mod by nitec", result.stderr)
        self.assertIn("--mod-dll", result.stderr)
        self.assertEqual(self.ini.read_bytes(), INI_ORIGINAL)

    def test_enable_anr_switches_ini_and_keeps_coopmat(self):
        self.install_ok()
        self.make_anr_tree()
        self.enable_ok("--fsr4", "lite", "--fg", "anr")
        self.assertEqual(self.ini.read_bytes(), EXPECTED_ANR)
        state = (self.root / "profiles" / "cyberpunk2077" / "state.conf").read_text()
        self.assertIn("FSR4=lite\n", state)
        self.assertIn("FG=anr\n", state)
        self.assertIn("KEEP_COOPMAT=1\n", state)

    @unittest.skipUnless(shutil.which("unzip"), "unzip is missing, needed to extract the zips")
    def test_enable_from_official_archives_then_disable(self):
        import zipfile
        self.install_ok()
        (self.game / "dxgi.dll").unlink()
        (self.game / "OptiScaler.ini").unlink()

        opti_zip = self.tmp / "OptiScaler-v10.zip"
        with zipfile.ZipFile(opti_zip, "w") as archive:
            archive.writestr("OptiScaler/dxgi.dll", b"optiscaler proxy\n")
            archive.writestr("OptiScaler/OptiScaler.ini", INI_ORIGINAL)
            archive.writestr("OptiScaler/OptiScaler/D3D12_OptiScaler/D3D12Core.dll",
                             b"agility core\n")
        anr_zip = self.tmp / "anr-addon.zip"
        with zipfile.ZipFile(anr_zip, "w") as archive:
            archive.writestr("Apex Neural Rendering FG/dlssg/nvngx_dlssg.dll",
                             b"anr dlssg\n")

        self.set_profile(
            MOD_SHA256=self.sha(self.game / "amd_fidelityfx_upscaler_dx12.dll"),
            MOD_SIZE=str((self.game / "amd_fidelityfx_upscaler_dx12.dll").stat().st_size),
            FSR_ORIGINAL_SHA256=self.sha(self.game / "fsr-original.dll"),
            FSR_ORIGINAL_SIZE=str((self.game / "fsr-original.dll").stat().st_size),
            OPTISCALER_SHA256=self.sha(opti_zip),
            ANR_SHA256=self.sha(anr_zip),
        )
        self.enable_ok("--fsr4", "int8", "--fg", "anr",
                       "--optiscaler", str(opti_zip), "--anr", str(anr_zip))
        self.assertEqual(self.ini.read_bytes(), EXPECTED_ANR)
        self.assertTrue((self.game / "dxgi.dll").is_file())
        self.assertTrue((self.game / "OptiScaler" / "D3D12_OptiScaler"
                         / "D3D12Core.dll").is_file())
        self.assertTrue((self.game / "OptiScaler" / "custom"
                         / "Apex Neural Rendering FG" / "dlssg"
                         / "nvngx_dlssg.dll").is_file())
        manifest = (self.backup_dirs()[0] / "manifest.tsv").read_text()
        self.assertIn("added\tOptiScaler.ini", manifest)
        self.assertIn("added\tOptiScaler/custom/Apex Neural Rendering FG", manifest)

        self.run_cli("disable", str(self.game), check=True)
        self.assertFalse((self.game / "dxgi.dll").exists())
        self.assertFalse(self.ini.exists())
        self.assertFalse((self.game / "OptiScaler").exists())
        self.assertFalse((self.game / "igdext64.dll").exists())
        self.assertTrue((self.game / "Cyberpunk2077.exe").is_file())

    @unittest.skipUnless(shutil.which("unzip"), "unzip is missing, needed to extract the zips")
    def test_enable_rejects_unpinned_optiscaler(self):
        import zipfile
        self.install_ok()
        (self.game / "dxgi.dll").unlink()
        other = self.tmp / "opti-raro.zip"
        with zipfile.ZipFile(other, "w") as archive:
            archive.writestr("dxgi.dll", b"otro dxgi\n")
        result = self.run_cli("enable", str(self.game), "--fsr4", "int8",
                              "--optiscaler", str(other))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not the expected file", result.stderr)
        self.assertFalse((self.game / "dxgi.dll").exists())

    def test_run_exports_expected_env(self):
        self.install_ok()
        self.enable_ok("--fsr4", "int8")
        result = self.run_cli("run", "--profile", "cyberpunk2077", "--", "env",
                              check=True)
        env = dict(line.split("=", 1) for line in result.stdout.splitlines()
                   if "=" in line)
        current = str(self.root / "current")
        self.assertEqual(env["VK_DRIVER_FILES"], current + "/icd/intel_icd.json")
        self.assertEqual(env["VK_LOADER_LAYERS_DISABLE"], "*")
        self.assertEqual(env["VKD3D_DISABLE_EXTENSIONS"], VKD3D_OFF)
        self.assertEqual(env["ANV_CM_HELPER"], current + "/tools/cm-compile.sh")
        self.assertEqual(env["ANV_CM_KERNEL_DIR"],
                         str(self.cache_dir / "fsr-xmx" / "1091500" / "kernels"))
        self.assertEqual(env["WINEDLLOVERRIDES"], "dxgi=n,b,cabinet=n,b")
        self.assertEqual(env["FSR4_XMX_INT8"], "1")
        self.assertEqual(env["FSR4_XMX_PROVIDER_INDEX"], "8")
        self.assertNotIn("FSR4_XMX_LITE", env)
        self.assertNotIn("VKD3D_KEEP_COOPMAT_EXTENSION", env)
        self.assertTrue(Path(env["ANV_CM_KERNEL_DIR"]).is_dir())

    def test_run_merges_winedlloverrides_and_anr_flag(self):
        self.install_ok()
        self.make_anr_tree()
        self.enable_ok("--fsr4", "lite", "--fg", "anr")
        result = self.run_cli("run", "--profile", "cyberpunk2077", "--", "env",
                              extra_env={"WINEDLLOVERRIDES": "d3d11=n,b"},
                              check=True)
        env = dict(line.split("=", 1) for line in result.stdout.splitlines()
                   if "=" in line)
        self.assertEqual(env["WINEDLLOVERRIDES"],
                         "d3d11=n,b,dxgi=n,b,cabinet=n,b")
        self.assertEqual(env["FSR4_XMX_LITE"], "1")
        self.assertEqual(env["FSR4_XMX_PROVIDER_INDEX"], "12")
        self.assertEqual(env["VKD3D_KEEP_COOPMAT_EXTENSION"], "1")

    def test_run_without_enable_fails_with_hint(self):
        self.install_ok()
        result = self.run_cli("run", "--profile", "cyberpunk2077", "--", "true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not set up", result.stderr)

    def test_run_without_profile_from_game_cwd(self):
        self.install_ok()
        self.enable_ok("--fsr4", "int8")
        result = self.run_cli("run", "--", "env", cwd=self.game, check=True)
        env = dict(line.split("=", 1) for line in result.stdout.splitlines()
                   if "=" in line)
        self.assertEqual(env["FSR4_XMX_INT8"], "1")
        self.assertEqual(env["VK_LOADER_LAYERS_DISABLE"], "*")

    def test_enable_anr_without_addon_fails(self):
        self.install_ok()
        result = self.run_cli("enable", str(self.game), "--fsr4", "int8",
                              "--fg", "anr")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("the ANR add-on is missing", result.stderr)
        self.assertIn("--anr", result.stderr)
        self.assertEqual(self.ini.read_bytes(), INI_ORIGINAL)

    def test_disable_restores_byte_identical(self):
        self.install_ok()
        self.make_anr_tree()
        self.enable_ok("--fsr4", "int8")
        self.enable_ok("--fsr4", "lite", "--fg", "anr")
        self.assertEqual(self.ini.read_bytes(), EXPECTED_ANR)

        result = self.run_cli("disable", str(self.game), check=True)
        self.assertIn("is back to how it was before", result.stdout)
        self.assertEqual(self.ini.read_bytes(), INI_ORIGINAL)
        self.assertFalse((self.game / "igdext64.dll").exists())
        self.assertFalse((self.game / "cabinet.dll").exists())
        self.assertFalse((self.root / "profiles" / "cyberpunk2077" / "state.conf").exists())
        self.assertTrue((self.root / "profiles" / "cyberpunk2077"
                         / "state.conf.disabled").exists())

        again = self.run_cli("disable", str(self.game))
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("no changes pending to undo", again.stderr)

    def test_disable_keeps_preexisting_cabinet(self):
        self.install_ok()
        (self.game / "cabinet.dll").write_bytes(b"the user's old cabinet\n")
        self.enable_ok("--fsr4", "int8")
        self.assertEqual((self.game / "cabinet.dll").read_bytes(), b"cabinet shim\n")
        self.run_cli("disable", str(self.game), check=True)
        self.assertEqual((self.game / "cabinet.dll").read_bytes(),
                         b"the user's old cabinet\n")

    def test_disable_keeps_the_state_pending_when_a_restore_fails(self):
        self.install_ok()
        self.enable_ok("--fsr4", "int8")
        backups = self.backup_dirs()
        self.assertEqual(len(backups), 1)
        saved = backups[0] / "files" / "OptiScaler.ini"
        original = saved.read_bytes()
        saved.unlink()

        result = self.run_cli("disable", str(self.game))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OptiScaler.ini", result.stdout)
        self.assertIn("Run disable again to retry them", result.stdout)
        self.assertIn("stays pending", result.stdout)
        self.assertEqual(self.state_key("PENDING_RESTORE"), "OptiScaler.ini")
        self.assertFalse((self.state_path().parent / "state.conf.disabled").exists())
        self.assertFalse((backups[0] / "applied").exists())
        self.assertEqual(self.ini.read_bytes(), EXPECTED_XEFG)

        saved.write_bytes(original)
        second = self.run_cli("disable", str(self.game))
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(self.ini.read_bytes(), INI_ORIGINAL)
        self.assertFalse(self.state_path().exists())
        self.assertTrue((self.state_path().parent / "state.conf.disabled").exists())

    def test_disable_retry_still_restores_the_original_ini(self):
        self.install_ok()
        self.enable_ok("--fsr4", "int8")
        self.make_anr_tree()
        self.enable_ok("--fsr4", "lite", "--fg", "anr")
        backups = self.backup_dirs()
        self.assertGreaterEqual(len(backups), 2)
        newest = backups[-1]
        saved = (newest / "files" / "OptiScaler.ini").read_bytes()
        (newest / "files" / "OptiScaler.ini").unlink()

        first = self.run_cli("disable", str(self.game))
        self.assertNotEqual(first.returncode, 0)
        self.assertFalse((backups[0] / "applied").exists())
        self.assertFalse((newest / "applied").exists())

        (newest / "files" / "OptiScaler.ini").write_bytes(saved)
        self.run_cli("disable", str(self.game), check=True)
        self.assertEqual(self.ini.read_bytes(), INI_ORIGINAL)

    @unittest.skipIf(os.geteuid() == 0, "root ignores file permissions")
    def test_disable_hides_tool_output_and_reports_each_failure_once(self):
        self.install_ok()
        self.enable_ok("--fsr4", "int8")
        os.chmod(self.ini, 0o444)
        os.chmod(self.game, 0o555)
        self.addCleanup(os.chmod, self.game, 0o755)
        self.addCleanup(os.chmod, self.ini, 0o644)

        result = self.run_cli("disable", str(self.game))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("rm:", result.stderr)
        self.assertNotIn("cp:", result.stderr)
        self.assertNotIn("should have been removed", result.stdout)
        self.assertNotIn("not identical to before", result.stdout)
        self.assertIn("couldn't restore OptiScaler.ini: permission denied",
                      result.stdout)
        self.assertIn("couldn't remove igdext64.dll: permission denied",
                      result.stdout)

    def test_compat_tool_swaps_vkd3d_and_vdf(self):
        self.install_ok()
        ge = self.make_ge_proton()
        result = self.run_cli("install-compat-tool", "--ge-dir", str(ge), check=True)
        self.assertIn("GE-Proton-XMX", result.stdout)
        tool = self.steam / "compatibilitytools.d" / "GE-Proton-XMX"
        dll = tool / "files" / "lib" / "wine" / "vkd3d-proton" / "x86_64-windows"
        self.assertEqual((dll / "d3d12.dll").read_bytes(), b"vkd3d d3d12\n")
        self.assertEqual((dll / "d3d12core.dll").read_bytes(), b"vkd3d d3d12core\n")
        vdf = (tool / "compatibilitytool.vdf").read_text()
        self.assertEqual(vdf.count('"display_name"'), 1)
        self.assertIn('"GE-Proton-XMX"', vdf)
        self.assertNotIn("GE-Proton11-12", vdf)
        manifest = (tool / ".fsr-xmx-manifest").read_text()
        self.assertIn("NAME=GE-Proton-XMX", manifest)
        self.assertIn("BASE_VERSION=GE-Proton11-12", manifest)
        doctor = self.run_cli("doctor")
        self.assertIn("OK      compatibility tool: GE-Proton-XMX",
                      doctor.stdout)

    def test_installer_text_has_no_spanish_leftovers(self):
        pattern = re.compile(
            r"[áéíóúñ¿¡]|\b(instal|carpeta|juego|prefijo|archivo|desinstal|"
            r"permiso|ruta|desconocida|herramienta|addon)\b", re.IGNORECASE)
        for path in (SCRIPT, COMMON, REPO / "installer" / "README.md"):
            text = path.read_text(encoding="utf-8")
            match = pattern.search(text)
            self.assertIsNone(
                match, "%s still has Spanish text: %r"
                % (path, match.group(0) if match else ""))

    def test_uninstall_removes_only_our_dirs(self):
        self.install_ok()
        ge = self.make_ge_proton()
        self.run_cli("install-compat-tool", "--ge-dir", str(ge), check=True)
        foreign = self.steam / "compatibilitytools.d" / "otra-cosa"
        foreign.mkdir()
        (foreign / "readme.txt").write_text("not ours\n")
        keep = self.data_dir / "otro-programa"
        keep.mkdir()

        self.enable_ok("--fsr4", "int8")
        refused = self.run_cli("uninstall")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("Games are still set up", refused.stdout)
        self.assertTrue(self.root.exists())

        self.run_cli("disable", str(self.game), check=True)
        result = self.run_cli("uninstall", check=True)
        self.assertIn("GE-Proton-XMX", result.stdout)
        self.assertFalse(self.root.exists())
        self.assertFalse((self.steam / "compatibilitytools.d" /
                          "GE-Proton-XMX").exists())
        self.assertTrue(foreign.is_dir())
        self.assertTrue(keep.is_dir())

    def test_uninstall_refuses_foreign_root(self):
        self.root.mkdir(parents=True)
        (self.root / "algo.txt").write_text("not ours\n")
        result = self.run_cli("uninstall")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("was not created by this program", result.stderr)
        self.assertTrue((self.root / "algo.txt").is_file())


if __name__ == "__main__":
    unittest.main()
