# Hardware Guide

How to build the Door Gate: the parts to buy, how to wire them to the Arduino, and how to load the Quickpass firmware.

The Arduino is a peripheral of the station computer. It reads Badges, drives the LCD, the LEDs, and the Door Gate motor, and does what the desktop program tells it over USB. It holds no attendance data and no School-facing text: the desktop program sends every LCD line in the School Language.

## Bill of materials

| Part | Quantity | Notes |
|:---|:---|:---|
| Arduino Uno R3 or compatible | 1 | With its USB cable. A Nano has the same pins and also works. |
| RC522 RFID reader module (MFRC522) | 1 | 13.56 MHz. Runs on **3.3 V only**. |
| RFID Badges | 1 per person | 13.56 MHz ISO 14443A tags, such as MIFARE Classic 1K cards or keyfobs. Many RC522 kits include a card and a keyfob. |
| 16x2 character LCD with an I2C backpack | 1 | HD44780-compatible display with a PCF8574 backpack at address `0x27` or `0x3F`. |
| 28BYJ-48 stepper motor (5 V) | 1 | Moves the Door Gate's latch or arm. |
| ULN2003 stepper driver board | 1 | Usually sold together with the motor. |
| Red LED and green LED | 1 each | Any standard 3 mm or 5 mm LEDs. |
| 220 Ω to 330 Ω resistors | 2 | One in series with each LED. |
| Regulated 5 V power supply, 1 A or more | 1 | Powers the motor driver. Its ground joins the Arduino's ground. |
| Breadboard and jumper wires | | |
| Station computer | 1 | Runs the desktop program. See [Desktop Setup](desktop-setup.md). |

## Wiring

![Door Gate Hardware Wiring and Pinout](images/hardware-wiring.svg)

### RFID reader: RC522 (SPI)

> [!WARNING]
> The RC522 runs on **3.3 V power and logic**. Connecting its VCC pin to 5 V permanently damages the reader.

| RC522 pin | Arduino pin | Notes |
|:---|:---|:---|
| **3.3V** | 3.3V | **Never 5 V** |
| **RST** | D9 | Reset line |
| **GND** | GND | Common ground |
| **IRQ** | Not connected | Unused |
| **MISO** | D12 | Hardware SPI |
| **MOSI** | D11 | Hardware SPI |
| **SCK** | D13 | Hardware SPI clock |
| **SDA (SS)** | D10 | SPI chip select |

### Display: 16x2 LCD with an I2C backpack

| Backpack pin | Arduino pin | Notes |
|:---|:---|:---|
| **GND** | GND | Ground |
| **VCC** | 5V | 5 V power |
| **SDA** | A4 | I2C data |
| **SCL** | A5 | I2C clock |

The firmware looks for the backpack at `0x27` first and then at `0x3F`. If the backlight is on but no text shows, turn the contrast potentiometer on the back of the backpack.

### Status LEDs

Connect each LED's long leg (anode) to the Arduino pin through its resistor, and its short leg (cathode) to GND.

| LED | Arduino pin | Resistor | Lights up when |
|:---|:---|:---|:---|
| **Red** | D2 | 220 Ω to 330 Ω to GND | Access is denied, for example for an unregistered Badge |
| **Green** | D3 | 220 Ω to 330 Ω to GND | Access is granted and the Door Gate opens |

### Door Gate motor: 28BYJ-48 with a ULN2003 driver

> [!IMPORTANT]
> The 28BYJ-48 draws up to about 350 mA while it turns. **Power the ULN2003 board from the external 5 V supply**, not from the Arduino's 5V pin, and connect the supply's ground to an Arduino GND pin (common ground).

| ULN2003 pin | Connects to | Notes |
|:---|:---|:---|
| **IN1** | D4 | Coil phase 1 |
| **IN2** | D5 | Coil phase 2 |
| **IN3** | D6 | Coil phase 3 |
| **IN4** | D7 | Coil phase 4 |
| **+** | External 5 V supply (+) | Motor power |
| **-** | External 5 V supply (-) and Arduino GND | **Common ground is required** |

When it grants access, the firmware turns the motor 90° to open the Door Gate. It keeps the gate open for the Door Dwell Time (10 seconds), then turns back 90° to close it. Another granted scan while the gate is open starts the 10 seconds again. The coils are switched off between moves so the motor doesn't overheat, which means the motor doesn't hold the latch in place, so use a latch that stays put on its own.

![DoorController Firmware State Machine](images/door-gate-lifecycle.svg)

To change the timing or the angle, edit these constants in `main_program/main_program.ino` and upload again:

| Constant | Default | Meaning |
|:---|:---|:---|
| `DOOR_DWELL_MS` | `10000` | Door Dwell Time, in milliseconds |
| `DENY_DWELL_MS` | `3000` | How long a denial or a short message stays on the LCD |
| `STEPS_90_DEG` | `512` | Motor steps for the 90° turn |

## Arduino libraries

Install these with the Arduino IDE's Library Manager (**Tools > Manage Libraries...**) or with `arduino-cli`:

1. **`MFRC522`** by GithubCommunity, version 1.4.10 or later.
2. **`LiquidCrystal_I2C`** by Martin Kubovčík, version 2.0.0 or later (MIT License).
   - The older **`LiquidCrystal I2C`** by Frank de Brabander (with a space in its name) installs a header with the same name, `LiquidCrystal_I2C.h`, into the same folder. If you have it, uninstall it first. It has no license, so Quickpass doesn't use it.

`SPI` and `Wire` come with the Arduino AVR core.

## Uploading the firmware

### With the Arduino IDE

1. Connect the Arduino to the computer with its USB cable.
2. Open `main_program/main_program.ino` in the Arduino IDE.
3. Choose the board under **Tools > Board > Arduino AVR Boards > Arduino Uno** (or your Nano).
4. Choose the port under **Tools > Port**: `COM3` or similar on Windows, `/dev/cu.usbmodem...` on macOS.
5. Click **Upload**.

### With `arduino-cli`

Install the AVR core and the libraries once:

```bash
arduino-cli core install arduino:avr
arduino-cli lib uninstall "LiquidCrystal I2C"     # only if Frank de Brabander's library is installed
arduino-cli lib install "MFRC522"
arduino-cli lib install "LiquidCrystal_I2C@2.0.0"
```

Then compile and upload for an Arduino Uno with the flashing script (macOS, Linux, or Git Bash on Windows):

```bash
./main_program/tools/flash.sh                       # the port comes from SERIAL_PORT in .env, or is detected
./main_program/tools/flash.sh /dev/cu.usbmodem11101 # or give the port yourself
```

Or run the two `arduino-cli` steps yourself:

```bash
arduino-cli compile --fqbn arduino:avr:uno main_program
arduino-cli upload --port COM3 --fqbn arduino:avr:uno main_program
```

Use `arduino:avr:nano` as the board for a Nano.

## Checking the board

Open the Arduino IDE's Serial Monitor at **9600 baud** with the **Newline** line ending. After a reset, the LCD shows `QUICKPASS` over `Connecting...` until the desktop program sends its standby screen, and the Arduino prints its boot lines. The RFID version number varies from chip to chip:

```
--- QUICKPASS BOOTING ---
INIT_SPI...
RFID_VERSION: 0x92
RFID_OK
INIT_LCD...
LCD_OK:0x27
QUICKPASS_READY
```

Then try each part:

- Type `IDLE QUICKPASS|Tap your badge`. The LCD shows the standby screen.
- Tap a Badge on the reader. The Arduino prints `SCAN` and the Badge UID, such as `SCAN 23F5A89B`.
- Type `GRANT Test User|On Time`. The green LED lights, and the Door Gate opens for 10 seconds and closes.
- Type `DENY ACCESS DENIED|Unregistered`. The red LED lights for 3 seconds.

The diagnostic tool does the same from a terminal, and lists the computer's serial ports if it can't open the one you give it:

```bash
python main_program/tools/diagnostic.py --port /dev/cu.usbmodem11101
```

It shows what the Arduino sends, and accepts `idle <line 1>|<line 2>`, `grant <line 1>|<line 2>`, `deny <header>|<reason>`, `unlock`, `msg <line 1>|<line 2>`, `raw <text>`, and `q` to quit.

> [!WARNING]
> Only one program can use the serial port at a time. **Close the Serial Monitor and the diagnostic tool before starting Quickpass.**

[Architecture](architecture.md#serial-protocol) describes every line the Arduino and the desktop program exchange.

## Troubleshooting

| What you see | What to check |
|:---|:---|
| `RFID_NOT_DETECTED` | The RC522's 3.3V and GND wires, and pins D9 to D13. |
| `LCD_NOT_DETECTED` | The LCD's 5V, GND, SDA (A4), and SCL (A5) wires. The backpack's address must be `0x27` or `0x3F`. The Door Gate still works without the LCD. |
| `I2C_BUS_ERROR` | SDA or SCL is held low. Look for a short or a swapped wire on A4 and A5. |
| The backlight is on but there's no text | Turn the contrast potentiometer on the backpack. |
| The motor hums, shakes, or skips steps | The external 5 V supply, the common ground, and the IN1 to IN4 order. |
| Quickpass can't open the port | Close the Serial Monitor or the diagnostic tool, and check `SERIAL_PORT` in `.env`. |
