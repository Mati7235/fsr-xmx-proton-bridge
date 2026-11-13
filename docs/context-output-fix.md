# D3D12 legacy context output fix

## Finding

At the original pinned revision `ef39559d26e083ce1bd1353b2e8c86f33c3c264c`,
both `_INTC_D3D12_CreateDeviceExtensionContext` and
`_INTC_D3D12_CreateDeviceExtensionContext1` accept `INTCExtensionInfo` (192 bytes
in the 64-bit Windows ABI), adapt its requested version into
`INTCExtensionInfo1` (200 bytes), and pass the latter to
`D3D12ExtensionContext::InitExtensions`. That initializer fills the device
information and three driver outputs in `INTCExtensionInfo1`. Before this fix,
neither API copied any output back to the caller.

Upstream `662dc6e8787c1e9ed43e09ef73733046bc1b8dc3` (commit `8f45d12`) now
copies exactly those fields inline in both legacy exports. The candidate is
therefore no longer a behavioral addition on this base: it keeps the same copy
in the shared `CopyExtensionInfo1OutputsToOld` helper and replaces the two
inline copies with calls to it, so `0003` has one routine to reuse. The
copy-back still happens only after successful initialization; failure and ABI
behavior are unchanged.

The base device-info member has a compatible prefix. However, the driver output
members are eight bytes later in `INTCExtensionInfo1` because
`INTCDeviceInfo1` adds the GMD fields. The patch assigns each of the seven
shared device-info fields (including the fixed-size generation-name array) and
the three driver outputs individually; it never copies the extended structure
wholesale or exposes its GMD-only tail.
Copy-back happens only after successful initialization, preserving the caller's
requested-version input and leaving outputs untouched on failure. D3D11 and
`_INTC_D3D12_CreateDeviceExtensionContext2` are not changed.

## Reproduction and verification

The builder pins the source SHA-256 and emits
`patches/0002-shim-context-output.patch` deterministically:

```sh
python tools/build_context_output_patch.py
python -m unittest -v tests.test_context_output
```

The targeted tests check pinned revision/hash, deterministic output, patch
application, and rejection of changed source. A compile-only Clang Windows
target check uses the actual upstream `igdext.h` without C++ standard headers
or a Windows SDK, asserting the 192/200-byte layouts and relevant offsets. A
separate host CPU executable uses `-fshort-wchar`, the real header, and the
actual generated helper and both generated D3D12 function bodies with small
stubs. It checks requested-version forwarding, output values, success/failure
paths, and surrounding canaries.
The CPU test also checks that the entire caller output remains unchanged after
failure, and keeps a negative control that removes the (now upstream) inline
copy so the harness still detects the original missing-copy regression.

These are ABI/layout and deterministic CPU tests only. They do not compile the
complete shim against the Windows SDK, run a DLL, or demonstrate driver,
Proton, injection, or GPU behavior. The CPU stubs model the initializer's
outputs; they do not execute the upstream `D3D12ExtensionContext` implementation.

The coordinator additionally [cross-built the complete patched shim](shim-cross-build.md)
with LLVM-MinGW in an isolated source copy. That is an offline compilation/link
check, not a Windows SDK/MSVC build or runtime validation. The patch remains a
candidate: it has not been installed in upstream, a prefix or a game.

## Known pre-existing reuse limitation

The patch fixes output propagation when a D3D12 context half is initialized.
Both legacy exports still return early with `S_OK` when the supplied context
already contains a D3D12 half. That upstream path neither initializes nor copies
device/driver outputs into a fresh caller structure. It remains unfixed; do not
interpret this patch as complete API conformance for repeated creation calls.
Changing reuse semantics safely requires a separate decision about cached
information, requested-version validation and device identity, rather than
blindly reinitializing a live context. The CPU harness characterizes this path
explicitly so the limitation is not mistaken for tested output propagation.
