/* StrList helpers declared in regex_helpers.h but emitted static-inline in regex_helpers.c. */

#include "regex_helpers.h"
#include <stdlib.h>
#include <string.h>

void StrList_init(StrList *list) {
    list->data = NULL;
    list->size = 0;
    list->capacity = 0;
}

void StrList_push(StrList *list, const char *item) {
    if (list->size + 1 > list->capacity) {
        size_t cap = list->capacity ? list->capacity * 2 : 8;
        list->data = (char **)realloc(list->data, cap * sizeof(char *));
        list->capacity = cap;
    }
    list->data[list->size++] = (char *)item;
}

size_t StrList_len(const StrList *list) {
    return list->size;
}

const char *StrList_get(const StrList *list, size_t index) {
    return list->data[index];
}
