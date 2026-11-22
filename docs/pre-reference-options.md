# PRE: what can serve as an independent reference

No new GPU tests were run for this evaluation. PRE and full FSR remain
unvalidated; there is no output oracle available yet.

## Functional reference

The most direct option is to capture the input and output resources of the
same PRE in a reference implementation that already works, together with
formats, views, kernel version, constants and geometry. A CPU implementation
would be another option, but it requires reconstructing the semantics and
validating them against that reference; translating isolated shader
operations is not enough.

A capture from the experimental bridge under Proton can provide the caller
contract and evidence of its bindings. **It does not automatically constitute
a correct reference output:** the path under investigation could already be
failing. Its provenance and degree of validation must be established.

## Binding cross-check with another Intel frontend

The zebin pinned for B580 (`3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2`)
contains metadata for stateful buffers, images and sampler. Level Zero exposes
`ZE_MODULE_FORMAT_NATIVE` and `zeModuleCreate`; its header and runtime
libraries are present locally. That makes it possible to investigate a second
loading path, **but it does not demonstrate that this particular zebin is
accepted**.

Running the same kernel through Level Zero or OpenCL could cross-check the
bridge's ABI against a different shim/ANV frontend, with identical inputs and
a byte-by-byte comparison. It would not be an independent algorithmic
implementation: it would keep the kernel and possibly the same compiler.
Moreover, Intel's OpenCL and Level Zero share the NEO core, so comparing the
two does not provide two fully independent references.

Architecture source: [Intel Compute Runtime](https://github.com/intel/compute-runtime/blob/master/ARCHITECTURE.md).
The presence of libraries does not prove that an ICD is usable, nor does it
authorize enumerating devices or loading modules during offline inspection.

## Next offline gate for that alternative

Before preparing an experiment with another frontend:

1. Identify the revision/version of the installed Compute Runtime and its
   compatibility with the pinned IGC/ocloc; review its zebin parser and the
   `.ze_info` version.
2. Trace the conversion of the twelve arguments into API objects, BTIs and
   sampler. Do not assume that an exposed API accepts all the particularities
   of the CM kernel.
3. Resolve the formats/views, contents, sizes and geometry that are still
   missing.
4. Design readback, canaries and an independent comparison before the GPU
   opt-in.

If that path is prepared, it will be recorded as a **binding/backend
cross-check**, not as mathematical validation of FSR. Creating the module or a
kernel without comparing its results does not close any functional gate. The
[PRE contract](pre-controlled-test-contract.md) remains the acceptance
criterion, and this evaluation does not authorize runtime.
