#include <cassert>
#include <cstring>
#include <iostream>
#include "../door_logic.h"

// Lines exactly as the desktop program sends them (arduino.command centers each LCD line).
static const char* IDLE_EN = "IDLE    QUICKPASS    | Tap your badge ";
static const char* IDLE_ES = "IDLE    QUICKPASS    | Acerque Carnet ";
static const char* GRANT_ANA = "GRANT   Welcome Ana   |    On Time     ";
static const char* MSG_ADDED = "MSG   Badge Added   |  Successfully  ";
static const char* DENY_UNREGISTERED = "DENY  ACCESS DENIED  |  Unregistered  ";
static const char* UNLOCK_REMOTE = "UNLOCK  Remote Access  |   Door Open    ";

void test_approval_while_closed_opens_door() {
    DoorController door;
    assert(door.get_state() == DoorState::CLOSED);
    assert(door.get_current_step() == 0);
    assert(!door.is_green_led_on());
    assert(!door.is_red_led_on());

    door.on_grant("Juan Perez", "On Time", 1000);

    assert(door.get_state() == DoorState::OPENING);
    assert(door.is_green_led_on());
    assert(!door.is_red_led_on());
    assert(door.get_motor_direction() == 1);
    assert(door.should_step_motor());
    assert(strstr(door.get_lcd_line1(), "Juan Perez") != nullptr);
    assert(strstr(door.get_lcd_line2(), "On Time") != nullptr);

    // Step motor to open
    while (door.get_state() == DoorState::OPENING) {
        int steps = door.get_pending_steps(16);
        assert(steps > 0);
        door.advance_motor(steps);
    }

    assert(door.get_state() == DoorState::OPEN);
    assert(door.get_current_step() == 512);
    assert(!door.should_step_motor());
    assert(door.is_green_led_on());
    assert(door.get_dwell_expire_ms() == 1000 + DoorController::DEFAULT_DOOR_DWELL_MS);
}

void test_approval_while_opening_or_open_restarts_timer_without_movement() {
    DoorController door;
    door.on_grant("First Person", "On Time", 1000);

    // Partially open
    door.advance_motor(100);
    assert(door.get_state() == DoorState::OPENING);
    assert(door.get_current_step() == 100);

    // Approval while opening
    door.on_grant("Second Person", "On Time", 1500);
    assert(door.get_state() == DoorState::OPENING);
    assert(strstr(door.get_lcd_line1(), "Second Person") != nullptr);
    // Finish opening
    while (door.get_state() == DoorState::OPENING) {
        door.advance_motor(door.get_pending_steps(16));
    }
    assert(door.get_state() == DoorState::OPEN);
    assert(door.get_current_step() == 512);

    // Approval while open
    unsigned long initial_expire = door.get_dwell_expire_ms();
    door.on_grant("Third Person", "Late", 6000);
    assert(door.get_state() == DoorState::OPEN);
    assert(door.get_current_step() == 512);
    assert(!door.should_step_motor());
    assert(door.get_motor_direction() == 0);
    assert(door.get_dwell_expire_ms() == 6000 + DoorController::DEFAULT_DOOR_DWELL_MS);
    assert(door.get_dwell_expire_ms() > initial_expire);
    assert(strstr(door.get_lcd_line1(), "Third Person") != nullptr);
}

void test_approval_while_closing_reopens_door() {
    DoorController door;
    door.on_grant("Student One", "On Time", 1000);
    door.advance_motor(512);
    assert(door.get_state() == DoorState::OPEN);

    // Let dwell expire
    door.update(1000 + DoorController::DEFAULT_DOOR_DWELL_MS);
    assert(door.get_state() == DoorState::CLOSING);
    assert(door.get_motor_direction() == -1);

    // Close partially
    door.advance_motor(200);
    assert(door.get_current_step() == 312);
    assert(door.get_state() == DoorState::CLOSING);

    // Approval while closing
    door.on_grant("Student Two", "On Time", 12000);
    assert(door.get_state() == DoorState::OPENING);
    assert(door.get_motor_direction() == 1);
    assert(door.get_current_step() == 312);
    assert(strstr(door.get_lcd_line1(), "Student Two") != nullptr);

    // Finish reopening
    while (door.get_state() == DoorState::OPENING) {
        door.advance_motor(door.get_pending_steps(16));
    }
    assert(door.get_state() == DoorState::OPEN);
    assert(door.get_current_step() == 512);
    assert(door.get_dwell_expire_ms() == 12000 + DoorController::DEFAULT_DOOR_DWELL_MS);
}

void test_denial_while_open_leaves_position_and_timer_and_clears_after_3s() {
    DoorController door;
    door.on_grant("Student One", "On Time", 1000);
    door.advance_motor(512);
    assert(door.get_state() == DoorState::OPEN);
    unsigned long expire_time = door.get_dwell_expire_ms();

    // Denial while open at t=5000
    door.on_deny("ACCESS DENIED", "Invalid Badge", 5000);
    assert(door.get_state() == DoorState::OPEN);
    assert(door.get_current_step() == 512);
    assert(door.get_dwell_expire_ms() == expire_time); // timer untouched
    assert(door.is_red_led_on());
    assert(door.is_green_led_on()); // green led still on because door is open
    assert(strstr(door.get_lcd_line1(), "ACCESS DENIED") != nullptr);
    assert(strstr(door.get_lcd_line2(), "Invalid Badge") != nullptr);

    // After 2.9 seconds: still denying
    door.update(7900);
    assert(door.is_red_led_on());
    assert(door.get_state() == DoorState::OPEN);

    // After 3.0 seconds: clears denial, restores previous grant screen
    door.update(8000);
    assert(!door.is_red_led_on());
    assert(door.is_green_led_on());
    assert(door.get_state() == DoorState::OPEN);
    assert(door.get_dwell_expire_ms() == expire_time);
    assert(strstr(door.get_lcd_line1(), "Student One") != nullptr);
}

void test_door_closes_when_dwell_time_runs_out() {
    DoorController door;
    door.on_grant("Student One", "On Time", 1000);
    door.advance_motor(512);
    assert(door.get_state() == DoorState::OPEN);

    // Before dwell expiry
    door.update(10999);
    assert(door.get_state() == DoorState::OPEN);

    // At dwell expiry (1000 + 10000 = 11000)
    door.update(11000);
    assert(door.get_state() == DoorState::CLOSING);
    assert(door.get_motor_direction() == -1);

    // Advance motor closing
    while (door.get_state() == DoorState::CLOSING) {
        door.advance_motor(door.get_pending_steps(16));
    }
    assert(door.get_state() == DoorState::CLOSED);
    assert(door.get_current_step() == 0);
    assert(!door.is_green_led_on());
    assert(strstr(door.get_lcd_line1(), "QUICKPASS") != nullptr);
}

void test_unlock_behaves_like_approval() {
    DoorController door;
    assert(door.get_state() == DoorState::CLOSED);

    door.on_unlock("Remote Access", "Door Open", 2000);
    assert(door.get_state() == DoorState::OPENING);
    assert(door.is_green_led_on());
    assert(strstr(door.get_lcd_line1(), "Remote Access") != nullptr);
    assert(strstr(door.get_lcd_line2(), "Door Open") != nullptr);

    door.advance_motor(512);
    assert(door.get_state() == DoorState::OPEN);
    assert(door.get_dwell_expire_ms() == 2000 + DoorController::DEFAULT_DOOR_DWELL_MS);
}

void test_msg_displays_text_without_moving_and_expires() {
    DoorController door;
    assert(door.get_state() == DoorState::CLOSED);

    door.on_msg("Badge Added", "  Successfully  ", 1000);
    assert(door.get_state() == DoorState::CLOSED);
    assert(!door.is_green_led_on());
    assert(!door.is_red_led_on());
    assert(!door.should_step_motor());
    assert(strstr(door.get_lcd_line1(), "Badge Added") != nullptr);
    assert(strstr(door.get_lcd_line2(), "Successfully") != nullptr);

    // After 2.9 seconds: still showing message
    door.update(3900);
    assert(strstr(door.get_lcd_line1(), "Badge Added") != nullptr);

    // After 3.0 seconds: returns to idle screen
    door.update(4000);
    assert(strstr(door.get_lcd_line1(), "QUICKPASS") != nullptr);
}

void test_boot_screen_shows_connecting_until_the_desktop_sends_idle() {
    DoorController door;
    assert(strcmp(door.get_lcd_line1(), "   QUICKPASS    ") == 0);
    assert(strcmp(door.get_lcd_line2(), " Connecting...  ") == 0);
}

void test_idle_command_replaces_the_standby_screen_at_once() {
    DoorController door;
    door.has_lcd_changed();

    door.on_command_line(IDLE_EN, 1000);
    assert(door.has_lcd_changed());
    assert(strcmp(door.get_lcd_line1(), "   QUICKPASS    ") == 0);
    assert(strcmp(door.get_lcd_line2(), " Tap your badge ") == 0);

    // A new School Language reaches the gate the same way, without re-flashing
    door.on_command_line(IDLE_ES, 2000);
    assert(strcmp(door.get_lcd_line2(), " Acerque Carnet ") == 0);
}

void test_idle_command_waits_until_the_door_closes_and_messages_end() {
    DoorController door;
    door.on_command_line(GRANT_ANA, 1000);
    door.on_command_line(IDLE_EN, 1500);
    assert(strstr(door.get_lcd_line1(), "Welcome Ana") != nullptr);

    door.advance_motor(512);
    door.update(door.get_dwell_expire_ms());
    assert(door.get_state() == DoorState::CLOSING);
    assert(strstr(door.get_lcd_line1(), "Welcome Ana") != nullptr);
    door.advance_motor(512);
    assert(door.get_state() == DoorState::CLOSED);
    assert(strcmp(door.get_lcd_line2(), " Tap your badge ") == 0);

    door.on_command_line(MSG_ADDED, 20000);
    door.on_command_line(IDLE_ES, 20500);
    assert(strstr(door.get_lcd_line1(), "Badge Added") != nullptr);
    door.update(20000 + DoorController::DEFAULT_DENY_DWELL_MS);
    assert(strcmp(door.get_lcd_line2(), " Acerque Carnet ") == 0);
}

void test_deny_command_shows_header_and_reason_then_the_idle_screen() {
    DoorController door;
    door.on_command_line(IDLE_EN, 0);

    door.on_command_line(DENY_UNREGISTERED, 1000);
    assert(door.is_red_led_on());
    assert(door.get_state() == DoorState::CLOSED);
    assert(strstr(door.get_lcd_line1(), "ACCESS DENIED") != nullptr);
    assert(strstr(door.get_lcd_line2(), "Unregistered") != nullptr);

    door.update(1000 + DoorController::DEFAULT_DENY_DWELL_MS);
    assert(!door.is_red_led_on());
    assert(strcmp(door.get_lcd_line2(), " Tap your badge ") == 0);
}

void test_unlock_command_opens_the_door_showing_its_lines() {
    DoorController door;
    door.on_command_line(UNLOCK_REMOTE, 2000);
    assert(door.get_state() == DoorState::OPENING);
    assert(door.is_green_led_on());
    assert(strstr(door.get_lcd_line1(), "Remote Access") != nullptr);
    assert(strstr(door.get_lcd_line2(), "Door Open") != nullptr);
}

void test_unknown_and_old_protocol_lines_change_nothing() {
    DoorController door;
    door.has_lcd_changed();

    door.on_command_line("GRANT:Carlos:On Time", 1000);
    door.on_command_line("VISIT:Ana:123", 1000);
    door.on_command_line("STATUS", 1000);

    assert(door.get_state() == DoorState::CLOSED);
    assert(!door.is_red_led_on());
    assert(!door.has_lcd_changed());
}

int main() {
    test_approval_while_closed_opens_door();
    test_approval_while_opening_or_open_restarts_timer_without_movement();
    test_approval_while_closing_reopens_door();
    test_denial_while_open_leaves_position_and_timer_and_clears_after_3s();
    test_door_closes_when_dwell_time_runs_out();
    test_unlock_behaves_like_approval();
    test_msg_displays_text_without_moving_and_expires();
    test_boot_screen_shows_connecting_until_the_desktop_sends_idle();
    test_idle_command_replaces_the_standby_screen_at_once();
    test_idle_command_waits_until_the_door_closes_and_messages_end();
    test_deny_command_shows_header_and_reason_then_the_idle_screen();
    test_unlock_command_opens_the_door_showing_its_lines();
    test_unknown_and_old_protocol_lines_change_nothing();
    std::cout << "All door logic tests passed successfully!" << std::endl;
    return 0;
}
