#include "FastIntentClassifier.h"
#include <string>
#include <algorithm>
#include <unordered_set>
#include <vector>
#include <cctype>

// Helper to lowercase and strip punctuation from a string
static std::string normalize_text(const std::string& input) {
    std::string result;
    result.reserve(input.size());
    bool last_was_space = false;
    
    for (char c : input) {
        // Strip punctuation and symbols like in Swift regex: [\p{P}\p{S}]+
        // std::ispunct checks for standard punctuation/symbols
        if (std::ispunct(static_cast<unsigned char>(c))) {
            if (!last_was_space && !result.empty()) {
                result += ' ';
                last_was_space = true;
            }
        } else if (std::isspace(static_cast<unsigned char>(c))) {
            if (!last_was_space && !result.empty()) {
                result += ' ';
                last_was_space = true;
            }
        } else {
            result += std::tolower(static_cast<unsigned char>(c));
            last_was_space = false;
        }
    }
    
    // Trim leading spaces
    size_t start = 0;
    while (start < result.size() && result[start] == ' ') {
        start++;
    }
    
    // Trim trailing spaces
    size_t end = result.size();
    while (end > start && result[end - 1] == ' ') {
        end--;
    }
    
    return result.substr(start, end - start);
}

int classify_intent_cpp(const char* text) {
    if (!text) return 0; // direct
    std::string norm = normalize_text(std::string(text));
    if (norm.empty()) return 0;

    // Check casual phrases
    static const std::unordered_set<std::string> casualPhrases = {
        "hi", "hello", "hey", "yo", "sup", "howdy",
        "good morning", "good afternoon", "good evening",
        "thanks", "thank you", "ok", "okay", "cool", "nice",
        "what are you", "who are you", "how are you"
    };

    if (casualPhrases.find(norm) != casualPhrases.end()) {
        return 1; // casual
    }

    // Split and check small tokens
    std::vector<std::string> tokens;
    std::string token;
    for (char c : norm) {
        if (c == ' ') {
            if (!token.empty()) {
                tokens.push_back(token);
                token.clear();
            }
        } else {
            token += c;
        }
    }
    if (!token.empty()) {
        tokens.push_back(token);
    }

    if (tokens.size() <= 3) {
        static const std::unordered_set<std::string> casualTokens = {
            "hi", "hello", "hey", "thanks", "yo", "ok", "okay"
        };
        bool all_casual = true;
        for (const auto& t : tokens) {
            if (casualTokens.find(t) == casualTokens.end()) {
                all_casual = false;
                break;
            }
        }
        if (all_casual && !tokens.empty()) {
            return 1; // casual
        }
    }

    if (text[0] == '/') {
        return 0; // direct
    }

    // Check web signals
    static const std::vector<std::string> webSignals = {
        "search web", "look up", "latest", "today", "news", "current", "recent",
        "find sources", "browse", "website", "url", "image search"
    };
    for (const auto& sig : webSignals) {
        if (norm.find(sig) != std::string::npos) {
            return 2; // web
        }
    }

    // Check agent signals
    static const std::vector<std::string> agentSignals = {
        "build", "create", "make", "implement", "fix", "debug", "change",
        "edit", "write files", "workspace", "app", "project", "run tests",
        "terminal", "code", "compile", "install"
    };
    for (const auto& sig : agentSignals) {
        if (norm.find(sig) != std::string::npos) {
            return 3; // agent
        }
    }

    return 0; // direct
}
