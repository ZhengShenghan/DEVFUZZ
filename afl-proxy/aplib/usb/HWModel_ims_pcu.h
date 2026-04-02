///
/// hardware model for ims_pcu
/// IMS Passenger Control Unit - USB CDC ACM device
/// VID: 0x04d8  PID: 0x0082 (application mode)
///

#include "HWModel.h"
#include "include/usb/desc.h"
#include "include/usb/usb.h"

#define USB_SFP_VID 0x04d8
#define USB_SFP_PID 0x0082

#define STRING_MANUFACTURER 1
#define STRING_PRODUCT 2
#define STRING_SERIALNUMBER 3
#define STRING_CONTROL 4
#define STRING_DATA 5

namespace ims_pcu {
static USBDescStrings usb_sfp_stringtable = {
    usb_sfp_stringtable[STRING_MANUFACTURER] = "IMS",
    usb_sfp_stringtable[STRING_PRODUCT] = "IMS PCU",
    usb_sfp_stringtable[STRING_SERIALNUMBER] = "sfpsfpsfpsfpsfpsfpsfp",
    usb_sfp_stringtable[STRING_CONTROL] = "IMS PCU Control",
    usb_sfp_stringtable[STRING_DATA] = "IMS PCU Data",
};

static USBDescIface desc_iface_sfp[] = {
    {/* CDC Control Interface (COMM) */
     .bInterfaceNumber = 0,
     .bNumEndpoints = 1,
     .bInterfaceClass = USB_CLASS_COMM,
     .bInterfaceSubClass = 0x02, /* USB_CDC_SUBCLASS_ACM */
     .bInterfaceProtocol = 0x01, /* USB_CDC_ACM_PROTO_AT_V25TER */
     .iInterface = STRING_CONTROL,
     .ndesc = 4,
     .descs =
         (USBDescOther[]){
             {
                 /* Header Functional Descriptor */
                 .data =
                     (uint8_t[]){
                         0x05,                /*  u8    bLength */
                         USB_DT_CS_INTERFACE, /*  u8    bDescriptorType */
                         0x00,                /*  u8    bDescriptorSubType - Header */
                         0x10, 0x01,          /*  le16  bcdCDC */
                     },
             },
             {
                 /* Call Management Functional Descriptor */
                 .data =
                     (uint8_t[]){
                         0x05,                /*  u8    bLength */
                         USB_DT_CS_INTERFACE, /*  u8    bDescriptorType */
                         0x01,                /*  u8    bDescriptorSubType - Call Mgmt */
                         0x00,                /*  u8    bmCapabilities */
                         0x01,                /*  u8    bDataInterface */
                     },
             },
             {
                 /* ACM Functional Descriptor */
                 .data =
                     (uint8_t[]){
                         0x04,                /*  u8    bLength */
                         USB_DT_CS_INTERFACE, /*  u8    bDescriptorType */
                         0x02,                /*  u8    bDescriptorSubType - ACM */
                         0x02,                /*  u8    bmCapabilities */
                     },
             },
             {
                 /* Union Functional Descriptor */
                 .data =
                     (uint8_t[]){
                         0x05,                /*  u8    bLength */
                         USB_DT_CS_INTERFACE, /*  u8    bDescriptorType */
                         0x06,                /*  u8    bDescriptorSubType - Union */
                         0x00,                /*  u8    bMasterInterface0 */
                         0x01,                /*  u8    bSlaveInterface0 */
                     },
             },
         },
     .eps = (USBDescEndpoint[]){
         {
             .bEndpointAddress = USB_DIR_IN | 0x01,
             .bmAttributes = USB_ENDPOINT_XFER_INT,
             .wMaxPacketSize = 0x08,
             .bInterval = 0xff,
         },
     }},
    {/* CDC Data Interface */
     .bInterfaceNumber = 1,
     .bNumEndpoints = 2,
     .bInterfaceClass = USB_CLASS_CDC_DATA,
     .bInterfaceSubClass = 0,
     .bInterfaceProtocol = 0,
     .iInterface = STRING_DATA,
     .eps = (USBDescEndpoint[]){
         {
             .bEndpointAddress = USB_DIR_OUT | 0x02,
             .bmAttributes = USB_ENDPOINT_XFER_BULK,
             .wMaxPacketSize = 0x40,
             .bInterval = 0,
         },
         {
             .bEndpointAddress = USB_DIR_IN | 0x03,
             .bmAttributes = USB_ENDPOINT_XFER_BULK,
             .wMaxPacketSize = 0x40,
             .bInterval = 0,
         },
     }},
};

static USBDescDevice desc_device_sfp = {
    .bcdUSB = 0x0200,
    .bDeviceClass = USB_CLASS_COMM,
    .bMaxPacketSize0 = 0x40,
    .bNumConfigurations = 1,
    .confs = (USBDescConfig[]){{
        .bNumInterfaces = 2,
        .bConfigurationValue = 1,
        .iConfiguration = 7,
        .bmAttributes = USB_CFG_ATT_ONE | USB_CFG_ATT_SELFPOWER,
        .bMaxPower = 0x32,
        .nif = ARRAY_SIZE(desc_iface_sfp),
        .ifs = desc_iface_sfp,
    }},
};

static USBDesc desc = {
    .id =
        {
            .idVendor = USB_SFP_VID,
            .idProduct = USB_SFP_PID,
            .bcdDevice = 0,
            .iManufacturer = STRING_MANUFACTURER,
            .iProduct = STRING_PRODUCT,
            .iSerialNumber = STRING_SERIALNUMBER,
        },
    // full speed usb device
    .full = &desc_device_sfp,
    .str = usb_sfp_stringtable,
};

static void *hw_model_usb_gen_desc() { return &desc; }
} // namespace ims_pcu
class HWModel_ims_pcu : public HWModel {
public:
  HWModel_ims_pcu()
      : HWModel("ims_pcu", USB_SFP_VID, USB_SFP_PID), probe_len(0) {}
  virtual ~HWModel_ims_pcu(){};
  virtual void restart_device() final { probe_len = 0; };
  virtual int read(uint8_t *dest, uint64_t addr, size_t size) final {
    uint8_t *ptr = &(device_ram[addr % sizeof(device_ram)]);
    switch (size) {
    case (1):
      *((uint8_t *)dest) = *(uint8_t *)(ptr);
      break;
    case (2):
      *((uint16_t *)dest) = *(uint16_t *)(ptr);
      break;
    case (4):
      *((uint32_t *)dest) = *(uint32_t *)(ptr);
      break;
    case (8):
      *((uint64_t *)dest) = *(uint64_t *)(ptr);
      break;
    default:
      /* USB bulk/interrupt transfers can be arbitrary sizes */
      memcpy(dest, ptr, size);
    }
    return size;
  };
  virtual void write(uint64_t data, uint64_t addr, size_t size) final {
    uint8_t *ptr = &device_ram[addr % sizeof(device_ram)];
    switch (size) {
    case (1):
      *ptr = (uint8_t)((data)&0xff);
      break;
    case (2):
      *((uint16_t *)ptr) = (uint16_t)((data)&0xffff);
      break;
    case (4):
      *((uint32_t *)ptr) = (uint32_t)((data)&0xffffffff);
      break;
    case (8):
      *((uint64_t *)ptr) = (uint64_t)(data);
      break;
    default:
      break;
    }
  };

  virtual void *getUSBDesc() { return ims_pcu::hw_model_usb_gen_desc(); }

private:
  int probe_len;
  uint8_t device_ram[1024000];
};
#undef USB_SFP_VID
#undef USB_SFP_PID
#undef STRING_MANUFACTURER
#undef STRING_PRODUCT
#undef STRING_SERIALNUMBER
#undef STRING_CONTROL
#undef STRING_DATA
// USB Protocol Model for ims_pcu
// Auto-extracted by generate_usb_model.py from LLVM bitcode
// Completion handlers: ims_pcu_irq
// Constraints: URB status, actual_length, response code 0xe0, protocol state
Stage2HWModel * new_stage2_model_ims_pcu() {
  unordered_map<int, HWInput> mmio_mdl = {};
  vector<DMAInputModel> dma_mdl = {};
  auto * model = new Stage2HWModel("ims_pcu", mmio_mdl, dma_mdl);

  // USB buffer protocol model (auto-extracted from driver bitcode)
  unordered_map<int, HWInput> usb_mdl =
  {
    {88 , HWInput(88, 4, {}, {0x0, 0xffffff94, 0xffffff98, 0xfffffffe}, {})},
    {132 , HWInput(132, 4, {}, {0x0}, {})},
    {208 , HWInput(208, 1, {}, {0xe0}, {})},
    {336 , HWInput(336, 1, {}, {}, {0x0, 0x1, 0x3, 0x4, 0xffffffffffffffff})},
    {337 , HWInput(337, 1, {}, {0x0}, {})},
    {338 , HWInput(338, 1, {}, {0x0}, {})},
    {339 , HWInput(339, 1, {}, {0x0}, {})},
    {1104 , HWInput(1104, 1, {}, {0x0}, {})},
  };
  model->setUSBModel(usb_mdl);

  return model;
}
