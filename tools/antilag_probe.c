/* Anti-Lag 2 probe: verifies VK_AMD_anti_lag exposure on ANV and measures
 * how long vkAntiLagUpdateAMD blocks (pacing) with maxFPS vs mode OFF.
 *
 * Build: cc tools/antilag_probe.c -lvulkan -o <scratch>/antilag_probe
 * Run:   VK_DRIVER_FILES=<scratch>/intel_icd.json <scratch>/antilag_probe
 */
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <vulkan/vulkan.h>

#define FRAMES 60

static double
now_s(void)
{
   struct timespec ts;
   clock_gettime(CLOCK_MONOTONIC, &ts);
   return ts.tv_sec + ts.tv_nsec * 1e-9;
}

int
main(void)
{
   VkApplicationInfo app = {
      .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
      .pApplicationName = "antilag_probe",
      .apiVersion = VK_API_VERSION_1_4,
   };
   VkInstanceCreateInfo ici = {
      .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
      .pApplicationInfo = &app,
   };
   VkInstance inst;
   if (vkCreateInstance(&ici, NULL, &inst) != VK_SUCCESS) {
      printf("FAIL: vkCreateInstance\n");
      return 1;
   }

   uint32_t gpu_count = 0;
   vkEnumeratePhysicalDevices(inst, &gpu_count, NULL);
   if (!gpu_count) {
      printf("FAIL: no physical devices\n");
      return 1;
   }
   VkPhysicalDevice gpus[8];
   uint32_t max_gpus = 8;
   if (gpu_count < max_gpus)
      max_gpus = gpu_count;
   vkEnumeratePhysicalDevices(inst, &max_gpus, gpus);
   VkPhysicalDevice phys = gpus[0];
   VkPhysicalDeviceProperties props;
   vkGetPhysicalDeviceProperties(phys, &props);
   printf("deviceName: %s\n", props.deviceName);
   printf("driverVersion: %u.%u.%u\n",
          VK_VERSION_MAJOR(props.driverVersion),
          VK_VERSION_MINOR(props.driverVersion),
          VK_VERSION_PATCH(props.driverVersion));

   uint32_t ext_count = 0;
   vkEnumerateDeviceExtensionProperties(phys, NULL, &ext_count, NULL);
   VkExtensionProperties exts[512];
   vkEnumerateDeviceExtensionProperties(phys, NULL, &ext_count, exts);
   int have_antilag_ext = 0;
   for (uint32_t i = 0; i < ext_count; i++) {
      if (!strcmp(exts[i].extensionName, "VK_AMD_anti_lag")) {
         have_antilag_ext = 1;
         printf("extension VK_AMD_anti_lag: present (spec %u)\n",
                exts[i].specVersion);
      }
   }
   if (!have_antilag_ext) {
      printf("extension VK_AMD_anti_lag: MISSING\n");
      return 1;
   }

   VkPhysicalDeviceAntiLagFeaturesAMD antiLagFeat = {
      .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ANTI_LAG_FEATURES_AMD,
   };
   VkPhysicalDeviceFeatures2 f2 = {
      .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2,
      .pNext = &antiLagFeat,
   };
   vkGetPhysicalDeviceFeatures2(phys, &f2);
   printf("feature antiLag: %s\n", antiLagFeat.antiLag ? "true" : "false");
   if (!antiLagFeat.antiLag) {
      printf("FAIL: antiLag feature not supported\n");
      return 1;
   }

   uint32_t qfam_count = 0;
   vkGetPhysicalDeviceQueueFamilyProperties(phys, &qfam_count, NULL);
   VkQueueFamilyProperties qfams[16];
   vkGetPhysicalDeviceQueueFamilyProperties(phys, &qfam_count, qfams);
   uint32_t qfam = 0;
   for (uint32_t i = 0; i < qfam_count; i++) {
      if (qfams[i].queueFlags & VK_QUEUE_GRAPHICS_BIT) {
         qfam = i;
         break;
      }
   }

   float prio = 1.0f;
   VkDeviceQueueCreateInfo qci = {
      .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
      .queueFamilyIndex = qfam,
      .queueCount = 1,
      .pQueuePriorities = &prio,
   };
   VkPhysicalDeviceAntiLagFeaturesAMD enableAntiLag = {
      .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ANTI_LAG_FEATURES_AMD,
      .antiLag = VK_TRUE,
   };
   const char *dev_exts[] = { "VK_AMD_anti_lag" };
   VkDeviceCreateInfo dci = {
      .sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
      .pNext = &enableAntiLag,
      .queueCreateInfoCount = 1,
      .pQueueCreateInfos = &qci,
      .enabledExtensionCount = 1,
      .ppEnabledExtensionNames = dev_exts,
   };
   VkDevice dev;
   VkResult r = vkCreateDevice(phys, &dci, NULL, &dev);
   if (r != VK_SUCCESS) {
      printf("FAIL: vkCreateDevice with VK_AMD_anti_lag (VkResult %d)\n", r);
      return 1;
   }
   printf("vkCreateDevice with VK_AMD_anti_lag: OK\n");

   PFN_vkAntiLagUpdateAMD pfn =
      (PFN_vkAntiLagUpdateAMD)vkGetDeviceProcAddr(dev, "vkAntiLagUpdateAMD");
   if (!pfn) {
      printf("FAIL: vkGetDeviceProcAddr(vkAntiLagUpdateAMD) returned NULL\n");
      return 1;
   }
   printf("vkAntiLagUpdateAMD: resolved\n");

   /* Mode ON, maxFPS=30, INPUT+PRESENT per frame with same frameIndex. */
   double t0 = now_s();
   for (uint64_t f = 0; f < FRAMES; f++) {
      VkAntiLagPresentationInfoAMD present = {
         .sType = VK_STRUCTURE_TYPE_ANTI_LAG_PRESENTATION_INFO_AMD,
         .stage = VK_ANTI_LAG_STAGE_INPUT_AMD,
         .frameIndex = f,
      };
      VkAntiLagDataAMD data = {
         .sType = VK_STRUCTURE_TYPE_ANTI_LAG_DATA_AMD,
         .mode = VK_ANTI_LAG_MODE_ON_AMD,
         .maxFPS = 30,
         .pPresentationInfo = &present,
      };
      pfn(dev, &data);
      present.stage = VK_ANTI_LAG_STAGE_PRESENT_AMD;
      pfn(dev, &data);
   }
   double t_on = now_s() - t0;
   printf("mode=ON maxFPS=30 frames=%d: %.3f s (%.1f ms/frame)\n",
          FRAMES, t_on, t_on * 1000.0 / FRAMES);

   /* Mode OFF: must not pace. */
   t0 = now_s();
   for (uint64_t f = 0; f < FRAMES; f++) {
      VkAntiLagPresentationInfoAMD present = {
         .sType = VK_STRUCTURE_TYPE_ANTI_LAG_PRESENTATION_INFO_AMD,
         .stage = VK_ANTI_LAG_STAGE_INPUT_AMD,
         .frameIndex = (uint64_t)FRAMES + f,
      };
      VkAntiLagDataAMD data = {
         .sType = VK_STRUCTURE_TYPE_ANTI_LAG_DATA_AMD,
         .mode = VK_ANTI_LAG_MODE_OFF_AMD,
         .maxFPS = 30,
         .pPresentationInfo = &present,
      };
      pfn(dev, &data);
      present.stage = VK_ANTI_LAG_STAGE_PRESENT_AMD;
      pfn(dev, &data);
   }
   double t_off = now_s() - t0;
   printf("mode=OFF maxFPS=30 frames=%d: %.3f s (%.1f ms/frame)\n",
          FRAMES, t_off, t_off * 1000.0 / FRAMES);

   vkDestroyDevice(dev, NULL);
   vkDestroyInstance(inst, NULL);

   int pass = (t_on > 1.0) && (t_off < 1.0);
   printf("RESULT: %s (expected ON ~= 2 s pacing, OFF << 1 s)\n",
          pass ? "PASS" : "CHECK");
   return pass ? 0 : 2;
}
