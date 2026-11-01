/* Linker script for a standalone Cortex-A9 application loaded at DDR 0x01000000. */
_STACK_SIZE = DEFINED(_STACK_SIZE) ? _STACK_SIZE : 0x4000;
_HEAP_SIZE = DEFINED(_HEAP_SIZE) ? _HEAP_SIZE : 0x2000;
_ABORT_STACK_SIZE = DEFINED(_ABORT_STACK_SIZE) ? _ABORT_STACK_SIZE : 1024;
_SUPERVISOR_STACK_SIZE = DEFINED(_SUPERVISOR_STACK_SIZE) ? _SUPERVISOR_STACK_SIZE : 2048;
_FIQ_STACK_SIZE = DEFINED(_FIQ_STACK_SIZE) ? _FIQ_STACK_SIZE : 1024;
_UNDEF_STACK_SIZE = DEFINED(_UNDEF_STACK_SIZE) ? _UNDEF_STACK_SIZE : 1024;

MEMORY
{
  ddr (rwx) : ORIGIN = 0x01000000, LENGTH = 0x3F000000
}

ENTRY(_vector_table)

SECTIONS
{
  .text : {
    *(.vectors) *(.boot) *(.text .text.*) *(.gnu.linkonce.t.*)
    *(.plt) *(.glue_7) *(.glue_7t) *(.vfp11_veneer)
    *(.ARM.extab) *(.gnu.linkonce.armextab.*)
  } > ddr

  .note.gnu.build-id : { KEEP(*(.note.gnu.build-id)) } > ddr
  .init : { KEEP(*(.init)) } > ddr
  .fini : { KEEP(*(.fini)) } > ddr

  .rodata : {
    __rodata_start = .;
    *(.rodata .rodata.*) *(.gnu.linkonce.r.*)
    __rodata_end = .;
  } > ddr

  /* Cortex-A9 short-descriptor L1 table: 4096 words, 16 KiB alignment.
     Leaving this as an orphan section made TTBR0 refer to the wrong base. */
  .mmu_tbl ALIGN(0x4000) : {
    KEEP(*(.mmu_tbl))
  } > ddr
  ASSERT((ADDR(.mmu_tbl) & 0x3fff) == 0, "MMU table must be 16 KiB aligned")
  ASSERT(SIZEOF(.mmu_tbl) == 0x4000, "Expected complete Cortex-A9 L1 table")

  .sdata2 : {
    __sdata2_start = .;
    *(.sdata2 .sdata2.*) *(.gnu.linkonce.s2.*)
    __sdata2_end = .;
  } > ddr

  .sbss2 (NOLOAD) : {
    __sbss2_start = .;
    *(.sbss2 .sbss2.*) *(.gnu.linkonce.sb2.*)
    __sbss2_end = .;
  } > ddr

  .data : {
    __data_start = .;
    *(.data .data.*) *(.gnu.linkonce.d.*) *(.jcr) *(.got .got.plt)
    __data_end = .;
  } > ddr

  .ctors : {
    __CTOR_LIST__ = .; ___CTORS_LIST___ = .;
    KEEP(*crtbegin.o(.ctors)) KEEP(*(EXCLUDE_FILE(*crtend.o) .ctors))
    KEEP(*(SORT(.ctors.*))) KEEP(*(.ctors));
    __CTOR_END__ = .; ___CTORS_END___ = .;
  } > ddr

  .dtors : {
    __DTOR_LIST__ = .; ___DTORS_LIST___ = .;
    KEEP(*crtbegin.o(.dtors)) KEEP(*(EXCLUDE_FILE(*crtend.o) .dtors))
    KEEP(*(SORT(.dtors.*))) KEEP(*(.dtors));
    __DTOR_END__ = .; ___DTORS_END___ = .;
  } > ddr

  .ARM.exidx : {
    __exidx_start = .; *(.ARM.exidx*); __exidx_end = .;
  } > ddr

  .preinit_array : {
    __preinit_array_start = .; KEEP(*(SORT(.preinit_array.*))) KEEP(*(.preinit_array));
    __preinit_array_end = .;
  } > ddr
  .init_array : {
    __init_array_start = .; KEEP(*(SORT(.init_array.*))) KEEP(*(.init_array));
    __init_array_end = .;
  } > ddr
  .fini_array : {
    __fini_array_start = .; KEEP(*(SORT(.fini_array.*))) KEEP(*(.fini_array));
    __fini_array_end = .;
  } > ddr

  .sdata : {
    __sdata_start = .;
    *(.sdata .sdata.*) *(.gnu.linkonce.s.*)
    __sdata_end = .;
  } > ddr
  .sbss (NOLOAD) : {
    __sbss_start = .;
    *(.sbss .sbss.*) *(.gnu.linkonce.sb.*)
    __sbss_end = .;
  } > ddr
  .bss (NOLOAD) : {
    __bss_start = .; __bss_start__ = .;
    *(.bss .bss.*) *(.gnu.linkonce.b.*) *(COMMON)
    __bss_end = .; __bss_end__ = .;
  } > ddr

  _SDA_BASE_ = __sdata_start + ((__sbss_end - __sdata_start) / 2);
  _SDA2_BASE_ = __sdata2_start + ((__sbss2_end - __sdata2_start) / 2);

  .heap (NOLOAD) : {
    . = ALIGN(16); _heap = .; HeapBase = .; _heap_start = .;
    . += _HEAP_SIZE; _heap_end = .; HeapLimit = .;
  } > ddr
  .stack (NOLOAD) : {
    . = ALIGN(16); _stack_end = .; . += _STACK_SIZE; _stack = .; __stack = _stack;
    . = ALIGN(16); _irq_stack_end = .; . += _STACK_SIZE; __irq_stack = .;
    _supervisor_stack_end = .; . += _SUPERVISOR_STACK_SIZE; . = ALIGN(16); __supervisor_stack = .;
    _abort_stack_end = .; . += _ABORT_STACK_SIZE; . = ALIGN(16); __abort_stack = .;
    _fiq_stack_end = .; . += _FIQ_STACK_SIZE; . = ALIGN(16); __fiq_stack = .;
    _undef_stack_end = .; . += _UNDEF_STACK_SIZE; . = ALIGN(16); __undef_stack = .;
  } > ddr
  _end = .;
}
