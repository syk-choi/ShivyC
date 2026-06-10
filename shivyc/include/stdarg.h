#ifndef _STDARG_H
#define _STDARG_H

/* ShivyC variadic support.
 *
 * Variadic functions in ShivyC receive all of their arguments on the stack
 * (see the calling-convention handling in the code generator), so a va_list
 * is just a moving pointer over those 8-byte argument slots. va_start asks the
 * compiler for the address of the first variadic argument; va_arg reads the
 * current slot and advances by one 8-byte slot. */

typedef char *va_list;

#define va_start(ap, last) ((ap) = (va_list)__builtin_va_start_addr())
#define va_arg(ap, type)   (*(type *)(((ap) = (ap) + 8), (ap) - 8))
#define va_end(ap)         ((void)((ap) = (va_list)0))
#define va_copy(dst, src)  ((dst) = (src))

#endif
