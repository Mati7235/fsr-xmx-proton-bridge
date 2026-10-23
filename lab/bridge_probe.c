/* Synthetic Vulkan DPAS/resource-map harness. Never dispatch without --run-gpu. */
#define _POSIX_C_SOURCE 200809L
#define _XOPEN_SOURCE 700
#include <vulkan/vulkan.h>

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define VENDOR_INTEL 0x8086u
#define DEVICE_BMG_G21 0xe20bu
#define BUFFER_COUNT 16u
#define WORDS_PER_BUFFER 128u
#define PUSH_BYTES 52u
#define CANARY_MAGIC 0x584d5843u
#define SENTINEL 0xa5c39e71u
#define ROOT_CONSTANT 0x434f4e53u
#define QUEUE_WAIT_TIMEOUT_NS 20000000000ull

static const uint32_t resource_slots[11] = {7, 8, 0, 1, 2, 3, 4, 5, 6, 9, 10};
static VkInstance instance;
static VkDevice device;
static VkBuffer buffers[BUFFER_COUNT];
static VkDeviceMemory memories[BUFFER_COUNT];
static void *mapped[BUFFER_COUNT];
static VkDescriptorPool descriptor_pool;
static VkDescriptorSetLayout descriptor_layout;
static VkDescriptorSet descriptor_set;
static VkPipelineLayout pipeline_layout;
static VkCommandPool command_pool;
static VkQueue queue;

static void
fail(const char *message)
{
   fprintf(stderr, "bridge_probe: %s\n", message);
   exit(EXIT_FAILURE);
}

static void
vk_check(VkResult result, const char *operation)
{
   if (result != VK_SUCCESS) {
      fprintf(stderr, "bridge_probe: %s failed: VkResult %d\n", operation, result);
      exit(EXIT_FAILURE);
   }
}

static int
redirect_stderr(const char *path)
{
   fflush(stderr);
   int saved = dup(STDERR_FILENO);
   if (saved < 0)
      fail("cannot save stderr for separated driver logs");
   /* The same phase log receives pipeline-compile and queue-submit diagnostics. */
   int fd = open(path, O_WRONLY | O_CREAT | O_APPEND, 0600);
   if (fd < 0) {
      close(saved);
      perror(path);
      fail("cannot create stage log (log directory must be new/empty)");
   }
   if (dup2(fd, STDERR_FILENO) < 0) {
      close(fd);
      close(saved);
      fail("cannot redirect stderr");
   }
   close(fd);
   return saved;
}

static void
restore_stderr(int saved)
{
   fflush(stderr);
   if (dup2(saved, STDERR_FILENO) < 0)
      fail("cannot restore stderr");
   close(saved);
}

static void
require_file(const char *path)
{
   struct stat st;
   if (stat(path, &st) != 0 || !S_ISREG(st.st_mode) || st.st_size == 0) {
      fprintf(stderr, "bridge_probe: missing or empty required file: %s\n", path);
      exit(EXIT_FAILURE);
   }
}

static uint32_t
find_memory_type(VkPhysicalDevice physical, uint32_t bits, VkMemoryPropertyFlags wanted)
{
   VkPhysicalDeviceMemoryProperties props;
   vkGetPhysicalDeviceMemoryProperties(physical, &props);
   for (uint32_t i = 0; i < props.memoryTypeCount; ++i)
      if ((bits & (1u << i)) &&
          (props.memoryTypes[i].propertyFlags & wanted) == wanted)
         return i;
   fail("no HOST_VISIBLE|HOST_COHERENT memory type for readback buffers");
   return 0;
}

static VkShaderModule
load_shader(const char *path)
{
   FILE *file = fopen(path, "rb");
   if (!file) {
      perror(path);
      fail("cannot open generated SPIR-V module");
   }
   if (fseek(file, 0, SEEK_END) != 0)
      fail("SPIR-V seek failed");
   long length = ftell(file);
   if (length < 20 || (length & 3) != 0 || fseek(file, 0, SEEK_SET) != 0)
      fail("SPIR-V must be a non-empty word-aligned module");
   uint32_t *code = malloc((size_t)length);
   if (!code || fread(code, 1, (size_t)length, file) != (size_t)length)
      fail("cannot read complete SPIR-V module");
   fclose(file);
   if (code[0] != 0x07230203u)
      fail("bad SPIR-V magic");
   VkShaderModuleCreateInfo info = {
      .sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
      .codeSize = (size_t)length,
      .pCode = code,
   };
   VkShaderModule module;
   VkResult result = vkCreateShaderModule(device, &info, NULL, &module);
   free(code);
   vk_check(result, "vkCreateShaderModule");
   return module;
}

static VkPipeline
make_pipeline(const char *spv_path, const char *entry, char *log_path)
{
   VkShaderModule module = load_shader(spv_path);
   VkPipelineShaderStageCreateInfo stage = {
      .sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
      .stage = VK_SHADER_STAGE_COMPUTE_BIT,
      .module = module,
      .pName = entry,
   };
   VkComputePipelineCreateInfo info = {
      .sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
      .stage = stage,
      .layout = pipeline_layout,
   };
   int saved = redirect_stderr(log_path);
   VkPipeline pipeline;
   VkResult result = vkCreateComputePipelines(device, VK_NULL_HANDLE, 1, &info, NULL, &pipeline);
   restore_stderr(saved);
   vkDestroyShaderModule(device, module, NULL);
   vk_check(result, "vkCreateComputePipelines");
   return pipeline;
}

static void
submit_once(VkPipeline pipeline, const uint32_t push[PUSH_BYTES / 4], const char *log_path)
{
   VkCommandBufferAllocateInfo alloc = {
      .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
      .commandPool = command_pool,
      .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY,
      .commandBufferCount = 1,
   };
   VkCommandBuffer cmd;
   vk_check(vkAllocateCommandBuffers(device, &alloc, &cmd), "vkAllocateCommandBuffers");
   VkCommandBufferBeginInfo begin = {
      .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
      .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT,
   };
   /* ANV emits dispatch traces while recording vkCmdDispatch, not just submitting. */
   int saved = redirect_stderr(log_path);
   vk_check(vkBeginCommandBuffer(cmd, &begin), "vkBeginCommandBuffer");
   vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
   vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline_layout,
                           0, 1, &descriptor_set, 0, NULL);
   vkCmdPushConstants(cmd, pipeline_layout, VK_SHADER_STAGE_COMPUTE_BIT, 0,
                      PUSH_BYTES, push);
   vkCmdDispatch(cmd, 1, 1, 1);
   VkMemoryBarrier barrier = {
      .sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER,
      .srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT,
      .dstAccessMask = VK_ACCESS_HOST_READ_BIT,
   };
   vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                        VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &barrier,
                        0, NULL, 0, NULL);
   vk_check(vkEndCommandBuffer(cmd), "vkEndCommandBuffer");
   VkSubmitInfo submit = {
      .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
      .commandBufferCount = 1,
      .pCommandBuffers = &cmd,
   };
   VkFenceCreateInfo fci = { .sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO };
   VkFence fence;
   vk_check(vkCreateFence(device, &fci, NULL, &fence), "vkCreateFence");
   VkResult result = vkQueueSubmit(queue, 1, &submit, fence);
   if (result == VK_SUCCESS)
      result = vkWaitForFences(device, 1, &fence, VK_TRUE, QUEUE_WAIT_TIMEOUT_NS);
   if (result == VK_TIMEOUT) {
      fprintf(stderr, "bridge_probe: GPU fence wait timed out after %" PRIu64
              " ns; no Vulkan cleanup/reset is attempted; inspect %s\n",
              (uint64_t)QUEUE_WAIT_TIMEOUT_NS, log_path);
      fflush(stderr);
      /* Do not call vkDeviceWaitIdle or destroy resources that may still be in use. */
      _Exit(124);
   }
   restore_stderr(saved);
   vk_check(result, "compute queue submit/fence wait");
   vkDestroyFence(device, fence, NULL);
   vkFreeCommandBuffers(device, command_pool, 1, &cmd);
}

static void
fill_sentinels(void)
{
   for (uint32_t b = 0; b < BUFFER_COUNT; ++b)
      for (uint32_t w = 0; w < WORDS_PER_BUFFER; ++w)
         ((uint32_t *)mapped[b])[w] = SENTINEL;
}

static bool
is_sentinel(uint32_t buffer)
{
   const uint32_t *words = mapped[buffer];
   for (uint32_t i = 0; i < WORDS_PER_BUFFER; ++i)
      if (words[i] != SENTINEL)
         return false;
   return true;
}

static bool
file_contains(const char *path, const char *needle)
{
   FILE *file = fopen(path, "rb");
   if (!file) return false;
   char line[1024];
   bool found = false;
   while (fgets(line, sizeof(line), file))
      if (strstr(line, needle)) { found = true; break; }
   fclose(file);
   return found;
}

static bool
direct_heap_layout_in_log(const char *path)
{
   FILE *file = fopen(path, "rb");
   if (!file) return false;
   char line[1024];
   unsigned set, binding, offset, stride, type;
   bool found = false;
   while (fgets(line, sizeof(line), file)) {
      if (sscanf(line, "ANV CM: heap set %u binding %u: descriptor offset %u stride %u (set layout type %u)",
                 &set, &binding, &offset, &stride, &type) == 5 &&
          set == 0 && binding == 0 && stride > 0 && type == 2 /* ANV DIRECT */) {
         found = true;
         break;
      }
   }
   fclose(file);
   return found;
}

static bool
path_is_within(const char *root, const char *path)
{
   const size_t n = strlen(root);
   return strncmp(root, path, n) == 0 && path[n] == '/';
}

static char *
read_icd_library_path(const char *manifest)
{
   FILE *file = fopen(manifest, "rb");
   if (!file) return NULL;
   if (fseek(file, 0, SEEK_END) != 0) { fclose(file); return NULL; }
   long size = ftell(file);
   if (size <= 0 || size > (1 << 20) || fseek(file, 0, SEEK_SET) != 0) {
      fclose(file);
      return NULL;
   }
   char *json = malloc((size_t)size + 1);
   if (!json || fread(json, 1, (size_t)size, file) != (size_t)size) {
      free(json);
      fclose(file);
      return NULL;
   }
   fclose(file);
   json[size] = '\0';
   char *key = strstr(json, "\"library_path\"");
   if (!key || !(key = strchr(key, ':'))) { free(json); return NULL; }
   while (*++key == ' ' || *key == '\t' || *key == '\r' || *key == '\n') {}
   if (*key++ != '"') { free(json); return NULL; }
   char *end = strchr(key, '"');
   if (!end || end == key) { free(json); return NULL; }
   char *library = strndup(key, (size_t)(end - key));
   free(json);
   return library;
}

static void
clear_inherited_prefix(const char *prefix)
{
   extern char **environ;
   const size_t prefix_len = strlen(prefix);
   for (char **entry = environ; *entry;) {
      if (strncmp(*entry, prefix, prefix_len) == 0) {
         char *equals = strchr(*entry, '=');
         if (equals) {
            char *name = strndup(*entry, (size_t)(equals - *entry));
            if (!name) fail("out of memory sanitizing inherited environment");
            if (unsetenv(name) != 0) {
               free(name);
               fail("cannot clear inherited driver environment");
            }
            free(name);
            continue; /* unsetenv shifts environ */
         }
      }
      ++entry;
   }
}

static void
write_evidence(const char *path, const char *text)
{
   FILE *file = fopen(path, "wx");
   if (!file) {
      perror(path);
      fail("cannot create non-overwriting evidence file");
   }
   if (fputs(text, file) == EOF || fclose(file) != 0)
      fail("cannot write evidence file");
}

static void
cleanup(void)
{
   if (device) {
      if (command_pool) vkDestroyCommandPool(device, command_pool, NULL);
      if (pipeline_layout) vkDestroyPipelineLayout(device, pipeline_layout, NULL);
      if (descriptor_pool) vkDestroyDescriptorPool(device, descriptor_pool, NULL);
      if (descriptor_layout) vkDestroyDescriptorSetLayout(device, descriptor_layout, NULL);
      for (uint32_t i = 0; i < BUFFER_COUNT; ++i) {
         if (mapped[i]) vkUnmapMemory(device, memories[i]);
         if (buffers[i]) vkDestroyBuffer(device, buffers[i], NULL);
         if (memories[i]) vkFreeMemory(device, memories[i], NULL);
      }
      vkDestroyDevice(device, NULL);
   }
   if (instance) vkDestroyInstance(instance, NULL);
}

static void
run_gpu(const char *probe_dir, const char *log_dir,
        const char *icd_manifest_arg, const char *icd_root_arg)
{
   char path[1024], marker[1024], kernel[1024], icd_log[1024], icd_evidence[1024];
   if (snprintf(path, sizeof(path), "%s/placeholder.spv", probe_dir) >= (int)sizeof(path) ||
       snprintf(marker, sizeof(marker), "%s/anv_canary", log_dir) >= (int)sizeof(marker) ||
       snprintf(kernel, sizeof(kernel), "%s/wg1_1_5.cmk", probe_dir) >= (int)sizeof(kernel))
      fail("path too long");
   if (snprintf(icd_log, sizeof(icd_log), "%s/icd-driver.log", log_dir) >= (int)sizeof(icd_log) ||
       snprintf(icd_evidence, sizeof(icd_evidence), "%s/icd-selection.txt", log_dir) >= (int)sizeof(icd_evidence))
      fail("path too long");
   char canary_spv[1024];
   if (snprintf(canary_spv, sizeof(canary_spv), "%s/canary.spv", probe_dir) >= (int)sizeof(canary_spv))
      fail("path too long");
   require_file(path);
   require_file(canary_spv);
   require_file(kernel);
   struct stat st;
   if (stat(marker, &st) == 0 || errno != ENOENT)
      fail("canary evidence path already exists or cannot be checked; use a fresh log directory");

   char *manifest = realpath(icd_manifest_arg, NULL);
   char *icd_root = realpath(icd_root_arg, NULL);
   if (!manifest || !icd_root) fail("cannot resolve explicit ICD manifest or local Mesa build root");
   if (stat(manifest, &st) != 0 || !S_ISREG(st.st_mode)) fail("ICD manifest is not a regular file");
   if (stat(icd_root, &st) != 0 || !S_ISDIR(st.st_mode)) fail("ICD root is not a directory");
   char *library_rel = read_icd_library_path(manifest);
   if (!library_rel) fail("cannot read a simple library_path string from ICD manifest");
   char library_candidate[PATH_MAX];
   if (library_rel[0] == '/') {
      if (snprintf(library_candidate, sizeof(library_candidate), "%s", library_rel) >= (int)sizeof(library_candidate))
         fail("ICD library path too long");
   } else {
      char manifest_dir[PATH_MAX];
      snprintf(manifest_dir, sizeof(manifest_dir), "%s", manifest);
      char *slash = strrchr(manifest_dir, '/');
      if (!slash) fail("ICD manifest has no containing directory");
      *slash = '\0';
      if (snprintf(library_candidate, sizeof(library_candidate), "%s/%s", manifest_dir, library_rel) >= (int)sizeof(library_candidate))
         fail("ICD library path too long");
   }
   free(library_rel);
   char *library = realpath(library_candidate, NULL);
   if (!library || stat(library, &st) != 0 || !S_ISREG(st.st_mode) || !path_is_within(icd_root, library))
      fail("ICD library must resolve to a regular file inside the supplied local Mesa build root");

   /* Remove inherited injection/loader selectors before setting this process's explicit values. */
   clear_inherited_prefix("ANV_CM_");
   unsetenv("VK_ADD_DRIVER_FILES");
   unsetenv("VK_LOADER_DRIVERS_SELECT");
   unsetenv("VK_LOADER_DRIVERS_DISABLE");
   unsetenv("VK_LAYER_PATH");
   unsetenv("VK_ADD_LAYER_PATH");
   unsetenv("VK_INSTANCE_LAYERS");
   unsetenv("VK_LOADER_LAYERS_ENABLE");
   unsetenv("VK_LOADER_LAYERS_DISABLE");
   unsetenv("VK_LAYER_SETTINGS_PATH");
   unsetenv("VK_LOADER_DEBUG");
   if (setenv("ANV_CM_KERNEL_DIR", probe_dir, 1) != 0 ||
       setenv("ANV_CM_SPV_DIR", log_dir, 1) != 0 ||
       setenv("ANV_CM_DEBUG", "1", 1) != 0 ||
       setenv("ANV_CM_TRACE", "1", 1) != 0 ||
       setenv("VK_DRIVER_FILES", manifest, 1) != 0 ||
       setenv("VK_ICD_FILENAMES", manifest, 1) != 0)
      fail("cannot set process-local driver/ICD environment");
   char selection[PATH_MAX * 3 + 128];
   snprintf(selection, sizeof(selection), "VK_DRIVER_FILES=%s\nmanifest=%s\nlibrary=%s\nroot=%s\n",
            manifest, manifest, library, icd_root);
   write_evidence(icd_evidence, selection);

   VkApplicationInfo app = {
      .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
      .pApplicationName = "synthetic bridge DPAS/resource-map probe",
      .applicationVersion = 1,
      .pEngineName = "bridge_probe",
      .engineVersion = 1,
      .apiVersion = VK_API_VERSION_1_1,
   };
   VkInstanceCreateInfo ici = {
      .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
      .pApplicationInfo = &app,
   };
   int icd_saved = redirect_stderr(icd_log);
   vk_check(vkCreateInstance(&ici, NULL, &instance), "vkCreateInstance");
   restore_stderr(icd_saved);
   uint32_t count = 0;
   vk_check(vkEnumeratePhysicalDevices(instance, &count, NULL), "vkEnumeratePhysicalDevices(count)");
   if (count == 0) fail("no Vulkan physical devices; refusing to run");
   VkPhysicalDevice *physical = calloc(count, sizeof(*physical));
   if (!physical) fail("out of memory enumerating physical devices");
   vk_check(vkEnumeratePhysicalDevices(instance, &count, physical), "vkEnumeratePhysicalDevices(list)");
   VkPhysicalDevice gpu = VK_NULL_HANDLE;
   VkPhysicalDeviceProperties props = {0};
   for (uint32_t i = 0; i < count; ++i) {
      VkPhysicalDeviceProperties candidate;
      vkGetPhysicalDeviceProperties(physical[i], &candidate);
      if (candidate.vendorID == VENDOR_INTEL && candidate.deviceID == DEVICE_BMG_G21) {
         gpu = physical[i];
         props = candidate;
         break;
      }
   }
   free(physical);
   if (!gpu) fail("required PCI vendor/device 8086:e20b not found; no GPU work submitted");
   fprintf(stdout, "Target Vulkan device: %s (PCI %04x:%04x)\n", props.deviceName,
           props.vendorID, props.deviceID);

   uint32_t family_count = 0;
   vkGetPhysicalDeviceQueueFamilyProperties(gpu, &family_count, NULL);
   VkQueueFamilyProperties *families = calloc(family_count, sizeof(*families));
   if (!families) fail("out of memory enumerating queues");
   vkGetPhysicalDeviceQueueFamilyProperties(gpu, &family_count, families);
   uint32_t family = UINT32_MAX;
   for (uint32_t i = 0; i < family_count; ++i)
      if (families[i].queueCount && (families[i].queueFlags & VK_QUEUE_COMPUTE_BIT)) { family = i; break; }
   free(families);
   if (family == UINT32_MAX) fail("target device has no compute queue");
   float priority = 1.0f;
   VkDeviceQueueCreateInfo qci = {
      .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
      .queueFamilyIndex = family,
      .queueCount = 1,
      .pQueuePriorities = &priority,
   };
   VkDeviceCreateInfo dci = {
      .sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
      .queueCreateInfoCount = 1,
      .pQueueCreateInfos = &qci,
   };
   vk_check(vkCreateDevice(gpu, &dci, NULL, &device), "vkCreateDevice");
   vkGetDeviceQueue(device, family, 0, &queue);

   VkDescriptorSetLayoutBinding binding = {
      .binding = 0,
      .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
      .descriptorCount = BUFFER_COUNT,
      .stageFlags = VK_SHADER_STAGE_COMPUTE_BIT,
   };
   VkDescriptorSetLayoutCreateInfo dlci = {
      .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
      .bindingCount = 1,
      .pBindings = &binding,
   };
   vk_check(vkCreateDescriptorSetLayout(device, &dlci, NULL, &descriptor_layout), "vkCreateDescriptorSetLayout");
   VkDescriptorPoolSize pool_size = { VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, BUFFER_COUNT };
   VkDescriptorPoolCreateInfo dpci = {
      .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,
      .maxSets = 1,
      .poolSizeCount = 1,
      .pPoolSizes = &pool_size,
   };
   vk_check(vkCreateDescriptorPool(device, &dpci, NULL, &descriptor_pool), "vkCreateDescriptorPool");
   VkDescriptorSetAllocateInfo dsai = {
      .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,
      .descriptorPool = descriptor_pool,
      .descriptorSetCount = 1,
      .pSetLayouts = &descriptor_layout,
   };
   vk_check(vkAllocateDescriptorSets(device, &dsai, &descriptor_set), "vkAllocateDescriptorSets");

   VkDescriptorBufferInfo dbi[BUFFER_COUNT];
   VkWriteDescriptorSet writes[BUFFER_COUNT];
   memset(writes, 0, sizeof(writes));
   for (uint32_t i = 0; i < BUFFER_COUNT; ++i) {
      VkBufferCreateInfo bci = {
         .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
         .size = WORDS_PER_BUFFER * sizeof(uint32_t),
         .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
         .sharingMode = VK_SHARING_MODE_EXCLUSIVE,
      };
      vk_check(vkCreateBuffer(device, &bci, NULL, &buffers[i]), "vkCreateBuffer");
      VkMemoryRequirements req;
      vkGetBufferMemoryRequirements(device, buffers[i], &req);
      uint32_t type = find_memory_type(gpu, req.memoryTypeBits,
                  VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
      VkMemoryAllocateInfo mai = {
         .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
         .allocationSize = req.size,
         .memoryTypeIndex = type,
      };
      vk_check(vkAllocateMemory(device, &mai, NULL, &memories[i]), "vkAllocateMemory");
      vk_check(vkBindBufferMemory(device, buffers[i], memories[i], 0), "vkBindBufferMemory");
      vk_check(vkMapMemory(device, memories[i], 0, VK_WHOLE_SIZE, 0, &mapped[i]), "vkMapMemory");
      dbi[i] = (VkDescriptorBufferInfo){ buffers[i], 0, WORDS_PER_BUFFER * sizeof(uint32_t) };
      writes[i] = (VkWriteDescriptorSet){
         .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
         .dstSet = descriptor_set,
         .dstBinding = 0,
         .dstArrayElement = i,
         .descriptorCount = 1,
         .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
         .pBufferInfo = &dbi[i],
      };
   }
   vkUpdateDescriptorSets(device, BUFFER_COUNT, writes, 0, NULL);
   VkPushConstantRange range = { VK_SHADER_STAGE_COMPUTE_BIT, 0, PUSH_BYTES };
   VkPipelineLayoutCreateInfo plci = {
      .sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
      .setLayoutCount = 1,
      .pSetLayouts = &descriptor_layout,
      .pushConstantRangeCount = 1,
      .pPushConstantRanges = &range,
   };
   vk_check(vkCreatePipelineLayout(device, &plci, NULL, &pipeline_layout), "vkCreatePipelineLayout");
   VkCommandPoolCreateInfo cpci = {
      .sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
      .flags = VK_COMMAND_POOL_CREATE_TRANSIENT_BIT,
      .queueFamilyIndex = family,
   };
   vk_check(vkCreateCommandPool(device, &cpci, NULL, &command_pool), "vkCreateCommandPool");

   uint32_t push[PUSH_BYTES / 4] = {0};
   /* DWORD 0 is a recognizable scalar root parameter; DWORDs 1..11 are tables. */
   push[0] = ROOT_CONSTANT;
   for (uint32_t i = 0; i < 11; ++i) push[1 + i] = resource_slots[i];
   push[12] = 0xd00df00du; /* trailing sampler/dummy DWORD, intentionally not a resource table */

   char canary_log[1024], probe_log[1024], canary_evidence[1024], readback[1024];
   if (snprintf(canary_log, sizeof(canary_log), "%s/canary-driver.log", log_dir) >= (int)sizeof(canary_log) ||
       snprintf(probe_log, sizeof(probe_log), "%s/probe-driver.log", log_dir) >= (int)sizeof(probe_log) ||
       snprintf(canary_evidence, sizeof(canary_evidence), "%s/canary-evidence.txt", log_dir) >= (int)sizeof(canary_evidence) ||
       snprintf(readback, sizeof(readback), "%s/probe-readback.txt", log_dir) >= (int)sizeof(readback))
      fail("path too long");

   fill_sentinels();
   VkPipeline canary = make_pipeline(canary_spv, "main", canary_log);
   submit_once(canary, push, canary_log);
   vkDestroyPipeline(device, canary, NULL);
   require_file(marker);
   if (!file_contains(marker, "patched ANV") || ((uint32_t *)mapped[0])[0] != CANARY_MAGIC)
      fail("canary recognition/marker readback failed");
   for (uint32_t b = 0; b < BUFFER_COUNT; ++b) {
      const uint32_t start = b == 0 ? 1 : 0;
      for (uint32_t w = start; w < WORDS_PER_BUFFER; ++w)
         if (((uint32_t *)mapped[b])[w] != SENTINEL)
            fail("canary changed a non-marker storage-buffer word");
   }
   write_evidence(canary_evidence,
      "Canary local_size=(1,1,17): patched ANV marker exists and contains 'patched ANV'; "
      "buffer 0 word 0 is 0x584d5843; every other word in all 16 buffers remains sentinel.\n");

   fill_sentinels();
   VkPipeline probe = make_pipeline(path, "main", probe_log);
   if (!file_contains(probe_log, "injected") || !direct_heap_layout_in_log(probe_log))
      fail("driver injection or set0/binding0 DIRECT heap-stride evidence missing; probe not dispatched");
   submit_once(probe, push, probe_log);
   vkDestroyPipeline(device, probe, NULL);
   if (!file_contains(probe_log, "dispatch kernel 1,1,5"))
      fail("driver dispatch log evidence missing; readback is not accepted alone");

   FILE *result = fopen(readback, "wx");
   if (!result) { perror(readback); fail("cannot create probe readback evidence"); }
   fprintf(result, "Synthetic DPAS/resource-map probe; 128 float32 words per output surface.\n");
   for (uint32_t slot = 0; slot < 11; ++slot) {
      uint32_t arg = 0;
      while (arg < 11 && resource_slots[arg] != slot) ++arg;
      if (arg == 11) fail("resource slot permutation is not bijective");
      const float expected = 16.0f + (float)arg;
      for (uint32_t w = 0; w < WORDS_PER_BUFFER; ++w) {
         float actual;
         memcpy(&actual, &((uint32_t *)mapped[slot])[w], sizeof(actual));
         if (actual != expected) {
            fprintf(stderr, "bridge_probe: output mismatch: heap slot %u word %u: got %.9g expected %.9g\n",
                    slot, w, actual, expected);
            fail("deterministic GPU readback mismatch");
         }
      }
      fprintf(result, "heap[%u]: all %u words == %g (argument %u)\n",
              slot, WORDS_PER_BUFFER, expected, arg);
   }
   for (uint32_t b = 11; b < BUFFER_COUNT; ++b)
      if (!is_sentinel(b)) fail("untouched heap slot 11..15 was modified");
   fprintf(result, "heap[11..15]: all words remain sentinel; canary passed; injection log evidence passed.\n");
   if (fclose(result) != 0) fail("cannot finish readback evidence");
   puts("GPU probe passed its gating, canary, injection-log, deterministic readback, and untouched-buffer checks.");
}

int
main(int argc, char **argv)
{
   bool run = false;
   const char *probe_dir = NULL, *log_dir = NULL, *icd_manifest = NULL, *icd_root = NULL;
   for (int i = 1; i < argc; ++i) {
      if (strcmp(argv[i], "--run-gpu") == 0) run = true;
      else if (strcmp(argv[i], "--probe-dir") == 0 && i + 1 < argc) probe_dir = argv[++i];
      else if (strcmp(argv[i], "--log-dir") == 0 && i + 1 < argc) log_dir = argv[++i];
      else if (strcmp(argv[i], "--icd-manifest") == 0 && i + 1 < argc) icd_manifest = argv[++i];
      else if (strcmp(argv[i], "--icd-root") == 0 && i + 1 < argc) icd_root = argv[++i];
      else fail("usage: bridge_probe [--run-gpu --probe-dir DIR --log-dir NEW_DIR --icd-manifest FILE --icd-root DIR]");
   }
   if (!run) {
      puts("CPU-only mode: no Vulkan instance/device created and no GPU work submitted. Pass --run-gpu explicitly to opt in.");
      return EXIT_SUCCESS;
   }
   if (!probe_dir || !log_dir || !icd_manifest || !icd_root)
      fail("--run-gpu requires --probe-dir, --log-dir, --icd-manifest, and --icd-root");
   if (mkdir(log_dir, 0700) != 0) {
      perror(log_dir);
      fail("--log-dir must be a new directory; evidence is never overwritten");
   }
   run_gpu(probe_dir, log_dir, icd_manifest, icd_root);
   cleanup();
   return EXIT_SUCCESS;
}
