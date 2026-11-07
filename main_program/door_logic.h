#ifndef DOOR_LOGIC_H
#define DOOR_LOGIC_H

#include <string.h>
#include <stdio.h>

#include "command_parser.h"

enum class DoorState {
    CLOSED,
    OPENING,
    OPEN,
    CLOSING
};

class DoorController {
public:
    static const unsigned long DEFAULT_DOOR_DWELL_MS = 10000;
    static const unsigned long DEFAULT_DENY_DWELL_MS = 3000;
    static const int DEFAULT_STEPS_90_DEG = 512;

    DoorController(unsigned long door_dwell = DEFAULT_DOOR_DWELL_MS,
                   unsigned long deny_dwell = DEFAULT_DENY_DWELL_MS,
                   int max_steps = DEFAULT_STEPS_90_DEG)
        : state_(DoorState::CLOSED),
          current_step_(0),
          max_steps_(max_steps),
          door_dwell_ms_(door_dwell),
          deny_dwell_ms_(deny_dwell),
          dwell_expire_ms_(0),
          deny_expire_ms_(0),
          msg_expire_ms_(0),
          last_now_ms_(0),
          is_denying_(false),
          is_showing_msg_(false),
          lcd_changed_(true) {
        lcd_line1_[0] = '\0';
        lcd_line2_[0] = '\0';
        saved_grant_line1_[0] = '\0';
        saved_grant_line2_[0] = '\0';
        // Until the desktop program sends its IDLE screen; English, like the boot lines on the serial port
        store_idle_lines("   QUICKPASS    ", " Connecting...  ");
        set_idle_screen();
    }

    DoorState get_state() const { return state_; }
    int get_current_step() const { return current_step_; }
    int get_max_steps() const { return max_steps_; }

    bool is_green_led_on() const {
        return state_ != DoorState::CLOSED;
    }

    bool is_red_led_on() const {
        return is_denying_;
    }

    const char* get_lcd_line1() const { return lcd_line1_; }
    const char* get_lcd_line2() const { return lcd_line2_; }

    bool has_lcd_changed() {
        bool changed = lcd_changed_;
        lcd_changed_ = false;
        return changed;
    }

    int get_motor_direction() const {
        if (state_ == DoorState::OPENING) return 1;
        if (state_ == DoorState::CLOSING) return -1;
        return 0;
    }

    bool should_step_motor() const {
        return get_motor_direction() != 0;
    }

    int get_pending_steps(int max_burst) const {
        if (state_ == DoorState::OPENING) {
            int remaining = max_steps_ - current_step_;
            if (remaining <= 0) return 0;
            return (remaining < max_burst) ? remaining : max_burst;
        } else if (state_ == DoorState::CLOSING) {
            int remaining = current_step_;
            if (remaining <= 0) return 0;
            return (remaining < max_burst) ? remaining : max_burst;
        }
        return 0;
    }

    void advance_motor(int steps) {
        if (state_ == DoorState::OPENING) {
            current_step_ += steps;
            if (current_step_ >= max_steps_) {
                current_step_ = max_steps_;
                state_ = DoorState::OPEN;
                dwell_expire_ms_ = last_now_ms_ + door_dwell_ms_;
            }
        } else if (state_ == DoorState::CLOSING) {
            current_step_ -= steps;
            if (current_step_ <= 0) {
                current_step_ = 0;
                state_ = DoorState::CLOSED;
                if (!is_denying_) {
                    set_idle_screen();
                }
            }
        }
    }

    // One line from the desktop program (see command_parser.h); any other line changes nothing.
    void on_command_line(const char* line, unsigned long now_ms) {
        ParsedCommandData cmd;
        parse_command_buf(line, cmd);
        switch (cmd.type) {
            case CommandType::IDLE:
                on_idle(cmd.line1, cmd.line2, now_ms);
                break;
            case CommandType::GRANT:
                on_grant(cmd.line1, cmd.line2, now_ms);
                break;
            case CommandType::DENY:
                on_deny(cmd.line1, cmd.line2, now_ms);
                break;
            case CommandType::UNLOCK:
                on_unlock(cmd.line1, cmd.line2, now_ms);
                break;
            case CommandType::MSG:
                on_msg(cmd.line1, cmd.line2, now_ms);
                break;
            default:
                break;
        }
    }

    // The standby screen; it waits for the door to close and for any denial or message to end.
    void on_idle(const char* line1, const char* line2, unsigned long now_ms) {
        last_now_ms_ = now_ms;
        store_idle_lines(line1, line2);
        if (state_ == DoorState::CLOSED && !is_denying_ && !is_showing_msg_) {
            set_idle_screen();
        }
    }

    void on_msg(const char* line1, const char* line2, unsigned long now_ms) {
        last_now_ms_ = now_ms;
        set_lcd(line1, line2);
        msg_expire_ms_ = now_ms + deny_dwell_ms_;
        is_showing_msg_ = true;
    }

    void on_grant(const char* line1, const char* line2, unsigned long now_ms) {
        last_now_ms_ = now_ms;
        set_granted_screen(line1, line2);

        // An approval clears any active denial or message screen immediately
        is_denying_ = false;
        is_showing_msg_ = false;

        if (state_ == DoorState::CLOSED) {
            state_ = DoorState::OPENING;
        } else if (state_ == DoorState::OPENING) {
            // Keep opening
        } else if (state_ == DoorState::OPEN) {
            // Restart dwell without more motor movement
            dwell_expire_ms_ = now_ms + door_dwell_ms_;
        } else if (state_ == DoorState::CLOSING) {
            // Reopen from current position
            state_ = DoorState::OPENING;
        }
    }

    void on_unlock(const char* line1, const char* line2, unsigned long now_ms) {
        on_grant(line1, line2, now_ms);
    }

    void on_deny(const char* header, const char* reason, unsigned long now_ms) {
        last_now_ms_ = now_ms;
        is_denying_ = true;
        is_showing_msg_ = false;
        deny_expire_ms_ = now_ms + deny_dwell_ms_;
        set_lcd(header, reason);
    }

    void update(unsigned long now_ms) {
        last_now_ms_ = now_ms;

        // Check denial expiry
        if (is_denying_ && now_ms >= deny_expire_ms_) {
            is_denying_ = false;
            // Restore previous screen
            if (state_ == DoorState::CLOSED) {
                set_idle_screen();
            } else {
                restore_granted_screen();
            }
        }

        // Check message expiry
        if (is_showing_msg_ && now_ms >= msg_expire_ms_) {
            is_showing_msg_ = false;
            if (state_ == DoorState::CLOSED && !is_denying_) {
                set_idle_screen();
            } else if (state_ != DoorState::CLOSED) {
                restore_granted_screen();
            }
        }

        // Check door dwell in OPEN state
        if (state_ == DoorState::OPEN) {
            if (now_ms >= dwell_expire_ms_) {
                state_ = DoorState::CLOSING;
            }
        }
    }

    unsigned long get_dwell_expire_ms() const { return dwell_expire_ms_; }

private:
    DoorState state_;
    int current_step_;
    int max_steps_;
    unsigned long door_dwell_ms_;
    unsigned long deny_dwell_ms_;
    unsigned long dwell_expire_ms_;
    unsigned long deny_expire_ms_;
    unsigned long msg_expire_ms_;
    unsigned long last_now_ms_;
    bool is_denying_;
    bool is_showing_msg_;
    bool lcd_changed_;

    char lcd_line1_[17];
    char lcd_line2_[17];

    char saved_grant_line1_[17];
    char saved_grant_line2_[17];

    char idle_line1_[17];
    char idle_line2_[17];

    void set_lcd(const char* l1, const char* l2) {
        char new_l1[17];
        char new_l2[17];
        snprintf(new_l1, sizeof(new_l1), "%-16.16s", l1 ? l1 : "");
        snprintf(new_l2, sizeof(new_l2), "%-16.16s", l2 ? l2 : "");

        if (strncmp(lcd_line1_, new_l1, 16) != 0 || strncmp(lcd_line2_, new_l2, 16) != 0) {
            memcpy(lcd_line1_, new_l1, 17);
            memcpy(lcd_line2_, new_l2, 17);
            lcd_changed_ = true;
        }
    }

    void store_idle_lines(const char* l1, const char* l2) {
        snprintf(idle_line1_, sizeof(idle_line1_), "%-16.16s", l1 ? l1 : "");
        snprintf(idle_line2_, sizeof(idle_line2_), "%-16.16s", l2 ? l2 : "");
    }

    void set_idle_screen() {
        set_lcd(idle_line1_, idle_line2_);
    }

    void set_granted_screen(const char* l1, const char* l2) {
        snprintf(saved_grant_line1_, sizeof(saved_grant_line1_), "%-16.16s", l1 ? l1 : "");
        snprintf(saved_grant_line2_, sizeof(saved_grant_line2_), "%-16.16s", l2 ? l2 : "");
        set_lcd(saved_grant_line1_, saved_grant_line2_);
    }

    void restore_granted_screen() {
        set_lcd(saved_grant_line1_, saved_grant_line2_);
    }
};

#endif // DOOR_LOGIC_H
