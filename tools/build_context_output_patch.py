#!/usr/bin/env python3
"""Build the context-output ABI candidate for the pinned upstream source."""
from __future__ import annotations

import argparse
import difflib
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = Path("shim/src/dll/IgdextApiDll.cpp")
SOURCE_SHA256 = "aed09d4fc616721216a46654b1501a6a2f7b93c0c198523f41fdba327c80ca96"


def once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"expected one source anchor, found {text.count(old)}: {old[:70]!r}")
    return text.replace(old, new, 1)


def build(source: str) -> str:
    # Old D3D12 exports accept INTCExtensionInfo; InitExtensions requires the
    # larger Info1. Copy only the old device base and old driver outputs on success.
    helper = """static void CopyExtensionInfo1OutputsToOld(INTCExtensionInfo& destination, const INTCExtensionInfo1& source)
{
    destination.IntelDeviceInfo.GPUMaxFreq = source.IntelDeviceInfo.GPUMaxFreq;
    destination.IntelDeviceInfo.GPUMinFreq = source.IntelDeviceInfo.GPUMinFreq;
    destination.IntelDeviceInfo.GTGeneration = source.IntelDeviceInfo.GTGeneration;
    destination.IntelDeviceInfo.EUCount = source.IntelDeviceInfo.EUCount;
    destination.IntelDeviceInfo.PackageTDP = source.IntelDeviceInfo.PackageTDP;
    destination.IntelDeviceInfo.MaxFillRate = source.IntelDeviceInfo.MaxFillRate;
    for (size_t i = 0; i < 64; ++i)
    {
        destination.IntelDeviceInfo.GTGenerationName[i] = source.IntelDeviceInfo.GTGenerationName[i];
    }
    destination.pDeviceDriverDesc = source.pDeviceDriverDesc;
    destination.pDeviceDriverVersion = source.pDeviceDriverVersion;
    destination.DeviceDriverBuildNumber = source.DeviceDriverBuildNumber;
}

"""
    source = once(source, "HRESULT _INTC_D3D12_CreateDeviceExtensionContext(", helper + "HRESULT _INTC_D3D12_CreateDeviceExtensionContext(")
    for name in ("_INTC_D3D12_CreateDeviceExtensionContext(", "_INTC_D3D12_CreateDeviceExtensionContext1("):
        start = source.index("HRESULT " + name)
        end = source.index("\n}\n", start)
        body = source[start:end]
        body = once(body,
                    "    // only RequestedExtensionVersion is meaningful since the stub never writes device info back.",
                    "    // Preserve the requested input; copy the compatible outputs back only on success.")
        body = once(body, "    *ppExtensionContext = pExtensionContext;\n\n    return result;",
                    "    CopyExtensionInfo1OutputsToOld(*pExtensionInfo, extensionInfo1);\n    *ppExtensionContext = pExtensionContext;\n\n    return result;")
        source = source[:start] + body + source[end:]

    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "upstream/xess-xmx-linux" / RELATIVE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data = args.source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SOURCE_SHA256:
        raise SystemExit(f"refusing unpinned source: SHA-256 {digest}; expected {SOURCE_SHA256}")
    before = data.decode("utf-8")
    after = build(before)
    patch = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                         fromfile="a/" + RELATIVE.as_posix(), tofile="b/" + RELATIVE.as_posix()))
    if args.output:
        with args.output.open("x") as stream:
            stream.write(patch)
    else:
        print(patch, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
