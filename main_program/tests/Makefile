CXX ?= c++
CXXFLAGS ?= -std=c++17 -Wall -Wextra -Werror

.PHONY: all test run clean

all: test

run: test

test: bin/test_parser bin/test_door_logic
	./bin/test_parser
	./bin/test_door_logic

bin/test_parser: test_parser.cpp ../command_parser.h
	@mkdir -p bin
	$(CXX) $(CXXFLAGS) test_parser.cpp -o bin/test_parser

bin/test_door_logic: test_door_logic.cpp ../door_logic.h
	@mkdir -p bin
	$(CXX) $(CXXFLAGS) test_door_logic.cpp -o bin/test_door_logic

clean:
	rm -rf bin
