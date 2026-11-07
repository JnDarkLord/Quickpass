#include <cassert>
#include <iostream>
#include <string>
#include "../command_parser.h"

// The desktop program centers both lines in 16 characters, as arduino.command() does.
static const std::string LINE1 = "   Hola, Ana    ";
static const std::string LINE2 = "    Puntual     ";

void test_every_screen_command_carries_two_lcd_lines_with_their_centering() {
    const struct { const char* word; CommandType type; } commands[] = {
        {"IDLE", CommandType::IDLE},
        {"GRANT", CommandType::GRANT},
        {"DENY", CommandType::DENY},
        {"UNLOCK", CommandType::UNLOCK},
        {"MSG", CommandType::MSG},
    };
    for (const auto& command : commands) {
        ParsedCommand cmd = parse_command(std::string(command.word) + " " + LINE1 + "|" + LINE2);
        assert(cmd.type == command.type);
        assert(cmd.line1 == LINE1);
        assert(cmd.line2 == LINE2);
    }
}

void test_bare_unlock_opens_with_empty_lines() {
    ParsedCommand cmd = parse_command("UNLOCK");
    assert(cmd.type == CommandType::UNLOCK);
    assert(cmd.line1.empty());
    assert(cmd.line2.empty());
}

void test_line_endings_are_dropped() {
    ParsedCommand cmd = parse_command("DENY ACCESS DENIED|Unregistered\r\n");
    assert(cmd.type == CommandType::DENY);
    assert(cmd.line1 == "ACCESS DENIED");
    assert(cmd.line2 == "Unregistered");
}

void test_text_without_a_separator_is_the_first_line() {
    ParsedCommand cmd = parse_command("MSG Badge Added");
    assert(cmd.type == CommandType::MSG);
    assert(cmd.line1 == "Badge Added");
    assert(cmd.line2.empty());
}

void test_lines_longer_than_the_lcd_are_cut_to_16_characters() {
    ParsedCommand cmd = parse_command("GRANT 12345678901234567890|abcdefghijklmnopqrstuvwxyz");
    assert(cmd.type == CommandType::GRANT);
    assert(cmd.line1 == "1234567890123456");
    assert(cmd.line2 == "abcdefghijklmnop");
}

void test_old_colon_protocol_and_unknown_words_are_ignored() {
    const char* ignored[] = {"GRANT:Carlos Santana:On Time", "DENY:Badge Expired", "MSG:Tarjeta:con Exito",
                             "VISIT:Ana:123", "GRANTED Ana|Late", "SOMETHING_ELSE", ""};
    for (const char* line : ignored) {
        assert(parse_command(line).type == CommandType::UNKNOWN);
    }
}

int main() {
    test_every_screen_command_carries_two_lcd_lines_with_their_centering();
    test_bare_unlock_opens_with_empty_lines();
    test_line_endings_are_dropped();
    test_text_without_a_separator_is_the_first_line();
    test_lines_longer_than_the_lcd_are_cut_to_16_characters();
    test_old_colon_protocol_and_unknown_words_are_ignored();
    std::cout << "All firmware parser tests passed successfully!" << std::endl;
    return 0;
}
