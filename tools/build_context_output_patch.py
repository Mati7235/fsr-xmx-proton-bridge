#!/usr/bin/env python3
"""Build the context-output ABI candidate for the pinned upstream source.

Upstream 662dc6e made the same output copy inline in both legacy D3D12 exports.
This builder emits the shared helper and replaces those inline copies with it,
so 0003 has one copy routine to reuse. The behavior stays equivalent.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = Path("shim/src/dll/IgdextApiDll.cpp")
SOURCE_SHA256 = "6d32d93487df60300de9e708b22c687ac8e58eba2dd1db1ef0f833d3dc252696"

# Upstream 662dc6e copies the shared outputs itself. Keep our helper as the
# single implementation (0003 reuses it) by replacing these inline copies.
UPSTREAM_COPY = """    // Hand the device and driver description back through the caller's (older, smaller) INTCExtensionInfo:
    // XeSS and XeLL use these entry points and read GTGeneration and the driver version string from it.
    pExtensionInfo->IntelDeviceInfo        = static_cast<const INTCDeviceInfo&>(extensionInfo1.IntelDeviceInfo);
    pExtensionInfo->pDeviceDriverDesc      = extensionInfo1.pDeviceDriverDesc;
    pExtensionInfo->pDeviceDriverVersion   = extensionInfo1.pDeviceDriverVersion;
    pExtensionInfo->DeviceDriverBuildNumber = extensionInfo1.DeviceDriverBuildNumber;
"""

UPSTREAM_COPY_NO_COMMENT = """    pExtensionInfo->IntelDeviceInfo        = static_cast<const INTCDeviceInfo&>(extensionInfo1.IntelDeviceInfo);
    pExtensionInfo->pDeviceDriverDesc      = extensionInfo1.pDeviceDriverDesc;
    pExtensionInfo->pDeviceDriverVersion   = extensionInfo1.pDeviceDriverVersion;
    pExtensionInfo->DeviceDriverBuildNumber = extensionInfo1.DeviceDriverBuildNumber;
"""

HELPER_CALL = "    CopyExtensionInfo1OutputsToOld(*pExtensionInfo, extensionInfo1);\n"


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
        if UPSTREAM_COPY in body:
            body = once(body, UPSTREAM_COPY, HELPER_CALL)
        elif UPSTREAM_COPY_NO_COMMENT in body:
            body = once(body, UPSTREAM_COPY_NO_COMMENT, HELPER_CALL)
        else:
            body = once(body,
                        "    // only RequestedExtensionVersion is meaningful since the stub never writes device info back.",
                        "    // Preserve the requested input; copy the compatible outputs back only on success.")
            body = once(body, "    *ppExtensionContext = pExtensionContext;\n\n    return result;",
                        HELPER_CALL + "    *ppExtensionContext = pExtensionContext;\n\n    return result;")
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
