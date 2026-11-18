# Verified LCD transport

Tested unit: HAVIT KB884L-TUR, `05AC:024F`, release descriptor `0111`, manufacturer `SONiX`, product `Gaming Keyboard`. These values do not identify its MCU or firmware version.

The application additionally verifies the report descriptors and that control/pixel interfaces belong to the same physical instance.

| Interface | Usage page | Payload |
|---|---|---|
| MI_03 | FF13 | 64-byte feature body plus report ID 0 |
| MI_02 | FF68 | 4096-byte output body plus report ID 0; 64-byte input acknowledgement |

The independently inspected Windows driver uses `04 18 → 04 72 → raw pages → 04 02`. The `04 72` header sets a selected list index and 16-bit page count. No live/RAM/region selector was found in this implementation. A separate `04 28` exchange carries clock/date and page selection; it is not an arbitrary text renderer.

Animation buffer:

- 256-byte header: byte 0 is frame count, bytes 1…N contain duration/2 ticks, remaining bytes FF.
- Each 160×96 frame occupies 30,720 bytes in little-endian RGB565.
- Up to 255 frames in the vendor format; conservative editor timing 30–500 ms per frame.
- Buffer is FF-padded to 4096-byte pages. Complete transfers wait for per-page acknowledgement.

The normal app exposes only the identified LCD and clock transactions. There is no firmware, erase, reset, generic-opcode or bootloader interface. Do not infer other-model compatibility from these constants.
