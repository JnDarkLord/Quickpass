/**
 * Quickpass Entrance Control & RFID Attendance Firmware
 *
 * Hardware components:
 * - RC522 RFID Reader (SPI: RST=9, SS/SDA=10, MOSI=11, MISO=12, SCK=13)
 * - 16x2 I2C Liquid Crystal Display (Address 0x27 or 0x3F, SDA=A4, SCL=A5)
 * - 28BYJ-48 Stepper Motor + ULN2003 Driver (IN1=4, IN2=5, IN3=6, IN4=7)
 * - Red LED (Pin 2) & Green LED (Pin 3)
 *
 * Communication Protocol (9600 baud, one line each, newline terminated):
 *   To the desktop:   SCAN <UID>, plus English boot lines (LCD_OK:0x27, RFID_OK, QUICKPASS_READY)
 *   From the desktop: IDLE <line 1>|<line 2>    the standby screen between scans
 *                     GRANT <line 1>|<line 2>   opens the door
 *                     DENY <header>|<reason>    lights the red LED for a moment
 *                     UNLOCK <line 1>|<line 2>  opens the door at a staff member's request
 *                     MSG <line 1>|<line 2>     shows the lines for a moment; the door stays shut
 * The desktop sends every LCD line in the School Language, so the sketch keeps no text of its own.
 */

#include <SPI.h>
#include <MFRC522.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

#include "door_logic.h"

// --- Hardware Pin Definitions ---
const int PIN_RED_LED   = 2;
const int PIN_GREEN_LED = 3;

const int PIN_STEPPER_IN1 = 4;
const int PIN_STEPPER_IN2 = 5;
const int PIN_STEPPER_IN3 = 6;
const int PIN_STEPPER_IN4 = 7;

const int PIN_RFID_RST = 9;
const int PIN_RFID_SS  = 10;

// --- Stepper Motor Parameters ---
const int STEPS_PER_REV = 2048;
const int STEPS_90_DEG  = 512;
const int MOTOR_BURST_STEPS = 16;

// 8-step half-stepping sequence for 28BYJ-48 stepper + ULN2003 driver.
// Native half-stepping provides maximum magnetic holding torque,
// completely eliminates vibration, and guarantees symmetrical bidirectional rotation.
const uint8_t HALF_STEP_SEQ[8][4] = {
    {HIGH, LOW,  LOW,  LOW }, // IN1
    {HIGH, HIGH, LOW,  LOW }, // IN1 + IN2
    {LOW,  HIGH, LOW,  LOW }, // IN2
    {LOW,  HIGH, HIGH, LOW }, // IN2 + IN3
    {LOW,  LOW,  HIGH, LOW }, // IN3
    {LOW,  LOW,  HIGH, HIGH}, // IN3 + IN4
    {LOW,  LOW,  LOW,  HIGH}, // IN4
    {HIGH, LOW,  LOW,  HIGH}  // IN4 + IN1
};

static int motorPhase = 0;

void stepMotorHalf(int dir) {
    if (dir > 0) {
        motorPhase = (motorPhase + 1) & 7;
    } else if (dir < 0) {
        motorPhase = (motorPhase + 7) & 7;
    }
    digitalWrite(PIN_STEPPER_IN1, HALF_STEP_SEQ[motorPhase][0]);
    digitalWrite(PIN_STEPPER_IN2, HALF_STEP_SEQ[motorPhase][1]);
    digitalWrite(PIN_STEPPER_IN3, HALF_STEP_SEQ[motorPhase][2]);
    digitalWrite(PIN_STEPPER_IN4, HALF_STEP_SEQ[motorPhase][3]);
}

void stepGateMotor(int dir, int steps) {
    for (int i = 0; i < steps; i++) {
        stepMotorHalf(dir);
        delayMicroseconds(1300);
        stepMotorHalf(dir);
        delayMicroseconds(1300);
    }
}

// --- Timing Constants ---
const unsigned long DOOR_DWELL_MS = 10000;
const unsigned long DENY_DWELL_MS = 3000;

// --- Hardware Instances ---
MFRC522 rfid(PIN_RFID_SS, PIN_RFID_RST);
LiquidCrystal_I2C lcd(0x27, 16, 2);

// --- Door Controller Instance ---
DoorController door(DOOR_DWELL_MS, DENY_DWELL_MS, STEPS_90_DEG);

bool lcdDetected = false;

// Serial input buffer
char serialBuffer[128];
byte bufferIndex = 0;

// Forward Declarations
void displayIdleScreen();
void deenergizeStepper();
void updateDoor();
void checkSerialInput();
void checkRfidScan();

void initLcdSafe() {
    // Check bus lines before Wire.begin to avoid I2C freeze if bus is low
    pinMode(A4, INPUT_PULLUP);
    pinMode(A5, INPUT_PULLUP);
    delay(10);
    if (digitalRead(A4) == LOW || digitalRead(A5) == LOW) {
        Serial.println("I2C_BUS_ERROR: SDA/SCL held LOW, skipping LCD");
        return;
    }

    Wire.begin();
    #if defined(WIRE_HAS_TIMEOUT)
    Wire.setWireTimeout(3000, true);
    #endif

    // Test address 0x27
    Wire.beginTransmission(0x27);
    if (Wire.endTransmission() == 0) {
        lcdDetected = true;
        lcd.init();
        lcd.backlight();
        displayIdleScreen();
        Serial.println("LCD_OK:0x27");
        return;
    }

    // Test alternate address 0x3F
    Wire.beginTransmission(0x3F);
    if (Wire.endTransmission() == 0) {
        lcdDetected = true;
        lcd = LiquidCrystal_I2C(0x3F, 16, 2);
        lcd.init();
        lcd.backlight();
        displayIdleScreen();
        Serial.println("LCD_OK:0x3F");
        return;
    }

    Serial.println("LCD_NOT_DETECTED (Running in serial-only mode)");
}

void setup() {
    Serial.begin(9600);
    delay(100);
    Serial.println("\n--- QUICKPASS BOOTING ---");

    // Initialize LED output pins
    pinMode(PIN_RED_LED, OUTPUT);
    pinMode(PIN_GREEN_LED, OUTPUT);
    digitalWrite(PIN_RED_LED, LOW);
    digitalWrite(PIN_GREEN_LED, LOW);

    // Initialize Stepper pins and motor speed
    pinMode(PIN_STEPPER_IN1, OUTPUT);
    pinMode(PIN_STEPPER_IN2, OUTPUT);
    pinMode(PIN_STEPPER_IN3, OUTPUT);
    pinMode(PIN_STEPPER_IN4, OUTPUT);
    deenergizeStepper();

    // Initialize SPI and MFRC522 RFID Reader
    Serial.println("INIT_SPI...");
    SPI.begin();
    rfid.PCD_Init();
    delay(50);

    // Print MFRC522 version info to verify SPI wiring
    byte v = rfid.PCD_ReadRegister(rfid.VersionReg);
    Serial.print("RFID_VERSION: 0x");
    Serial.println(v, HEX);
    if (v == 0x00 || v == 0xFF) {
        Serial.println("RFID_NOT_DETECTED (check 3.3V, GND, D9, D10, D11, D12, D13)");
    } else {
        Serial.println("RFID_OK");
    }

    // Initialize LCD safely
    Serial.println("INIT_LCD...");
    initLcdSafe();

    // Blink LEDs once to confirm boot complete
    digitalWrite(PIN_GREEN_LED, HIGH);
    digitalWrite(PIN_RED_LED, HIGH);
    delay(150);
    digitalWrite(PIN_GREEN_LED, LOW);
    digitalWrite(PIN_RED_LED, LOW);

    Serial.println("QUICKPASS_READY");
}

void loop() {
    checkSerialInput();
    checkRfidScan();
    updateDoor();
}

void displayIdleScreen() {
    if (!lcdDetected) return;
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print(door.get_lcd_line1());
    lcd.setCursor(0, 1);
    lcd.print(door.get_lcd_line2());
}

void deenergizeStepper() {
    digitalWrite(PIN_STEPPER_IN1, LOW);
    digitalWrite(PIN_STEPPER_IN2, LOW);
    digitalWrite(PIN_STEPPER_IN3, LOW);
    digitalWrite(PIN_STEPPER_IN4, LOW);
}

void updateDoor() {
    unsigned long now = millis();
    door.update(now);

    // Update LED indicators based on door state
    digitalWrite(PIN_GREEN_LED, door.is_green_led_on() ? HIGH : LOW);
    digitalWrite(PIN_RED_LED, door.is_red_led_on() ? HIGH : LOW);

    // Update LCD screen when text changes (overwrite without slow 25ms lcd.clear())
    if (lcdDetected && door.has_lcd_changed()) {
        lcd.setCursor(0, 0);
        lcd.print(door.get_lcd_line1());
        lcd.setCursor(0, 1);
        lcd.print(door.get_lcd_line2());
    }

    // Step motor in short bursts to keep RFID reader and serial responsive
    if (door.should_step_motor()) {
        int pending = door.get_pending_steps(MOTOR_BURST_STEPS);
        if (pending > 0) {
            // Invert motor direction polarity to match physical gate mounting:
            // OPENING steps negative (the direction that lifts the gate smoothly)
            // CLOSING steps positive (lowering the gate back down)
            int dir = -door.get_motor_direction();
            stepGateMotor(dir, pending);
            door.advance_motor(pending);
        }
        if (!door.should_step_motor()) {
            deenergizeStepper();
        }
    } else {
        deenergizeStepper();
    }
}

void checkSerialInput() {
    while (Serial.available() > 0) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            if (bufferIndex > 0) {
                serialBuffer[bufferIndex] = '\0';
                door.on_command_line(serialBuffer, millis());
                bufferIndex = 0;
            }
        } else if (bufferIndex < sizeof(serialBuffer) - 1) {
            serialBuffer[bufferIndex++] = c;
        }
    }
}

void checkRfidScan() {
    // Do not poll SPI/RFID while the stepper motor is actively moving to prevent bus jitter
    if (door.should_step_motor()) {
        return;
    }

    // Look for new cards
    if (!rfid.PICC_IsNewCardPresent()) {
        return;
    }
    // Select one of the cards
    if (!rfid.PICC_ReadCardSerial()) {
        return;
    }

    // Convert raw UID bytes into uppercase hex string
    char uidStr[32] = {0};
    int offset = 0;
    for (byte i = 0; i < rfid.uid.size && offset < (int)sizeof(uidStr) - 3; i++) {
        offset += snprintf(uidStr + offset, sizeof(uidStr) - offset, "%02X", rfid.uid.uidByte[i]);
    }

    // Send the scan to the desktop program
    Serial.print("SCAN ");
    Serial.println(uidStr);

    // Halt card communication and stop crypto
    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();
}
