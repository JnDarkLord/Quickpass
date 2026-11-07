#ifndef COMMAND_PARSER_H
#define COMMAND_PARSER_H

#include <string.h>
#include <ctype.h>

#if !defined(ARDUINO) && defined(__cplusplus)
#include <string>
#endif

// Lines from the desktop program: a command word, one space, then both LCD
// lines split by '|', such as `GRANT <line 1>|<line 2>`. The desktop centers
// each line in 16 characters, so the spaces around the text are kept.
enum class CommandType {
    IDLE,
    GRANT,
    DENY,
    UNLOCK,
    MSG,
    UNKNOWN
};

const size_t LCD_LINE_CHARS = 16;

struct ParsedCommandData {
    CommandType type;
    char line1[LCD_LINE_CHARS + 1];
    char line2[LCD_LINE_CHARS + 1];
};

inline bool command_word_is(const char* word, size_t length, const char* name) {
    return strlen(name) == length && strncmp(word, name, length) == 0;
}

inline void copy_lcd_line(char* dest, const char* start, const char* end) {
    size_t length = (size_t)(end - start);
    if (length > LCD_LINE_CHARS) length = LCD_LINE_CHARS;
    memcpy(dest, start, length);
    dest[length] = '\0';
}

inline void parse_command_buf(const char* input, ParsedCommandData& cmd) {
    cmd.type = CommandType::UNKNOWN;
    cmd.line1[0] = '\0';
    cmd.line2[0] = '\0';

    if (!input) return;

    // Skip leading whitespace and drop the line ending
    while (*input && isspace((unsigned char)*input)) input++;
    const char* end = input + strlen(input);
    while (end > input && (end[-1] == '\r' || end[-1] == '\n')) end--;

    const char* word_end = input;
    while (word_end < end && *word_end != ' ') word_end++;
    size_t word_length = (size_t)(word_end - input);

    if (command_word_is(input, word_length, "IDLE")) {
        cmd.type = CommandType::IDLE;
    } else if (command_word_is(input, word_length, "GRANT")) {
        cmd.type = CommandType::GRANT;
    } else if (command_word_is(input, word_length, "DENY")) {
        cmd.type = CommandType::DENY;
    } else if (command_word_is(input, word_length, "UNLOCK")) {
        cmd.type = CommandType::UNLOCK;
    } else if (command_word_is(input, word_length, "MSG")) {
        cmd.type = CommandType::MSG;
    } else {
        return;
    }

    // Exactly one space separates the word from the lines; any more belong to line 1
    const char* lines = (word_end < end) ? word_end + 1 : end;
    const char* separator = lines;
    while (separator < end && *separator != '|') separator++;

    copy_lcd_line(cmd.line1, lines, separator);
    if (separator < end) {
        copy_lcd_line(cmd.line2, separator + 1, end);
    }
}

#if !defined(ARDUINO) && defined(__cplusplus)
struct ParsedCommand {
    CommandType type;
    std::string line1;
    std::string line2;
};

inline ParsedCommand parse_command(const std::string& raw) {
    ParsedCommandData data;
    parse_command_buf(raw.c_str(), data);
    return ParsedCommand{data.type, std::string(data.line1), std::string(data.line2)};
}
#endif

#endif // COMMAND_PARSER_H
