#ifndef FAST_INTENT_CLASSIFIER_H
#define FAST_INTENT_CLASSIFIER_H

#ifdef __cplusplus
extern "C" {
#endif

// Returns:
// 0 = direct
// 1 = casual
// 2 = web
// 3 = agent
int classify_intent_cpp(const char* text);

#ifdef __cplusplus
}
#endif

#endif // FAST_INTENT_CLASSIFIER_H
