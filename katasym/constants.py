"""Constants reversed from the Katasymbol app.

All values verified against the decompiled Java source (see docs/03_print_protocol.md).
"""

# --- BLE UUIDs (canonical 128-bit form; the app uses short-form substring matching) ---

SERVICE_UUID_FEE7 = "0000fee7-0000-1000-8000-00805f9b34fb"   # primary for E10/T15
CHAR_UUID_FEC1    = "0000fec1-0000-1000-8000-00805f9b34fb"   # write + notify (same UUID)

SERVICE_UUID_E0FF = "0000e0ff-3c17-d293-8e48-14fe2e4da212"   # fallback set 1
CHAR_NOTIFY_FFE1  = "0000ffe1-0000-1000-8000-00805f9b34fb"
CHAR_WRITE_FFE9   = "0000ffe9-0000-1000-8000-00805f9b34fb"

SERVICE_UUID_FF00 = "0000ff00-0000-1000-8000-00805f9b34fb"   # fallback set 2
CHAR_NOTIFY_FF01  = "0000ff01-0000-1000-8000-00805f9b34fb"
CHAR_WRITE_FF02   = "0000ff02-0000-1000-8000-00805f9b34fb"

CCCD_UUID         = "00002902-0000-1000-8000-00805f9b34fb"

# --- E10 advertised-name allowlist (the device advertises its serial like "T0010") ---

E10_SERIALS: set[str] = {
    "T0007","T0010","T0011","T0012","T0017","T0025","T0026","T0027","T0028",
    "T0034","T0035","T0036","T0037","T0038","T0039","T0040","T0041","T0042",
    "T0043","T0044","T0045","T0057","T0058","T0059","T0060","T0061","T0064",
    "T0065","T0066","T0067","T0068","T0071","T0072","T0073","T0075","T0077",
    "T0078","T0081","T0082","T0083","T0084","T0085","T0086","T0087","T0088",
    "T0089","T0090","T0091","T0092","T0093","T0094","T0095","T0098","T0124",
    "T0125","T0126","T0127","T0130","T0131","T0132","T0133","T0134","T0135",
    "T0136","T0137","T0143","T0144","T0176","T0177","T0179","T0180","T0207",
    "T0208","T0209","T0210","T0222","T0223",
}

# --- Frame header ---

MAGIC_0 = 0x7E
MAGIC_1 = 0x5A
HEADER_BYTE_4 = 0x10              # always 0x10 in BasePrint.sendCmd (UnionPtg.sid value)
HEADER_BYTE_6 = 0xAA              # always 0xAA (signed -86 in Java source)

FRAME_TYPE_CMD = 0x01             # byte [5] for command frames
FRAME_TYPE_DATA = 0x02            # byte [5] for data-transfer frames (used by transferSplitData)

# --- Opcodes (BasePrint.java:59-119) ---

CMD_INQUIRY_STA              = 0x11   # default; 0x13 on TP70/TP76
CMD_BUF_FULL                 = 0x10
CMD_CHECK_DEVICE             = 0x12
CMD_START_PRINT              = 0x13
CMD_STOP_PRINT               = 0x14
CMD_RD_DEV_NAME              = 0x16
CMD_READ_REV                 = 0x17
CMD_STRD_MAT                 = 0x18
CMD_STRD_MAT_INFO            = 0x19
CMD_READ_DPI                 = 0x22
CMD_RD_LAB_YINWEI            = 0x24
CMD_SET_LAB_YINWEI           = 0x25
CMD_RD_HD_YINWEI             = 0x26
CMD_SET_HD_YINWEI            = 0x27
BLTCMD_HTIME_RD              = 0x2B
BLTCMD_HTIME_SET             = 0x2C
CMD_PAPER_SKIP               = 0x2E
CMD_RETURN_MAT               = 0x30
CMD_RD_DEV_DPI               = 0x31
CMD_SET_PRTMODE              = 0x33
CMD_SEND_INF                 = 0x35
CMD_SET_BLTCONTROL           = 0x37
CMD_SET_RL_YINWEI            = 0x38
CMD_SET_TB_YINWEI            = 0x39
CMD_READ_POWER_OFF_TIME      = 0x41
CMD_SET_POWER_OFF_TIME       = 0x42
CMD_READ_BUZZER_KEY          = 0x43
CMD_SET_BUZZER_KEY           = 0x44
CMD_RD_USER_INF              = 0x58
BLTCMD_NEXTFRM_BULK          = 0x5A
CMD_NEXT_ZIPPEDBULK          = 0x5C
CMD_SET_RFID_DATA            = 0x5D
CMD_ADJ_BCUT                 = 0x60
CMD_RD_DEV_OPT               = 0x67
CMD_WR_DEV_OPT               = 0x68
BLTCMD_RD_DEV_PAR            = 0x69
BLTCMD_WR_DEV_PAR            = 0x6A
CMD_SET_TIMESTAMP            = 0xB0
CMD_RD_TIMESTAMP             = 0xB1
CMD_RD_CONTINUE              = 0xB2
CMD_MAT_AUTHEN_RESULT        = 0xB6
CMD_PAPER_BACK               = 0xBA
CMD_CHECK_OPTLEVEL           = 0xBC
CMD_READ_OPTLEVEL            = 0xBD
CMD_SET_OPTLEVEL             = 0xBE
CMD_READ_FWVER               = 0xC5
CMD_START_FWUPDATA           = 0xC6
CMD_BLTCMD_SET_HEADRATE      = 0xC9   # used as "density" by T15Print (E10)
BLTCMD_START_FW_BUFFER_DATA  = 0xD0
BLTCMD_SEND_FW_BUFFER_DATA   = 0xD1
BLTCMD_UPDATA_FINISH         = 0xD2
CMD_FORCEUPDATE              = 0xD3
CMD_READ_RANDOM              = 0xD5
CMD_VERIFY_RANDOM            = 0xD6
CMD_BLTCMD_SET_DENSITY       = 0xD9   # alternate density opcode (not used by T15Print)

# --- DMA chunk frame ---

DMA_MAGIC_0   = 0xAA
DMA_MAGIC_1   = 0xBB
DMA_CHUNK_SIZE = 506                  # bytes of the inner DMA chunk (aa bb csum idx total + 500 data)
DMA_DATA_PER_CHUNK = 500              # payload bytes per chunk (rest = magic + csum + idx + total)
DMA_PAGE_SIZE = 512                   # passed as arg 1 to CMD_NEXT_ZIPPEDBULK

# --- DMA outer envelope (E10 / BLE devices) ---
# For bluetoothName containing "E" (E10), the 506-byte DMA chunk is wrapped in
# a 512-byte outer frame and split into 4×128-byte BLE writes (BasePrint.java:858-887).
DMA_ENVELOPE_SIZE = 512
DMA_ENVELOPE_HEADER = bytes([0x7E, 0x5A, 0xFC, 0x01, 0x10, 0x02])  # 6-byte fixed
DMA_BLE_SUBCHUNK = 128
DMA_BLE_SUBCHUNK_DELAY_S = 0.05       # 50 ms inter-write delay

# --- E10 device parameters (from E10Device.initDevice()) ---

E10_DPI = 8                           # 8 dots/mm == 203 dpi
E10_HEAD_DOTS = 96                    # printable width per "column" group
E10_BYTES_PER_COLUMN = 12             # 96 / 8 (mPerLineByte)
E10_CONCENTRATION_MIN = 1
E10_CONCENTRATION_MAX = 7
E10_COPIES_MIN = 1
E10_COPIES_MAX = 100
E10_VPOS_MIN = -9
E10_VPOS_MAX =  9
E10_HPOS_MIN = -9
E10_HPOS_MAX =  9
E10_PRINTER_TYPE = 15
E10_LANGUAGE = 2
E10_PACKAGE_TYPE = 3

# --- Defaults ---

DEFAULT_THRESHOLD = 125               # ImgConverter default
DEFAULT_MAT_SHIFT = 4                 # T15Print passes 4 to PAGE_REG_BITS.toByteArray
DEFAULT_MTU_REQUEST = 200             # BLEUtils.requestMtu(200); macOS may cap lower
