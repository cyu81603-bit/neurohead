param([string]$ToolBin='D:/Xilinx/Vitis/2022.2/gnu/aarch32/nt/gcc-arm-none-eabi/bin',[string]$Python='python')
$ErrorActionPreference='Stop'
. F:\NeuroHead\use_f_storage.ps1
$root=Split-Path $PSScriptRoot -Parent
$bsp=Join-Path $root 'support/bsp/ps7_cortexa9_0'
$tools=$ToolBin
$out=Join-Path $root 'build\firmware'
New-Item -ItemType Directory -Force -Path $out | Out-Null
$common=@('-mcpu=cortex-a9','-mfpu=vfpv3','-mfloat-abi=hard','-O2','-g','-Wall','-Wextra','-Werror','-ffreestanding','-I',"$bsp\include",'-I',"$root\src\ps")
$objects=@()
foreach($name in @('neurohead_udp_app','nh22_protocol','neurohead_platform_zynq')){
 $obj=Join-Path $out "$name.o"
 & "$tools\arm-none-eabi-gcc.exe" @common -c "$root\src\ps\$name.c" -o $obj
 if($LASTEXITCODE -ne 0){throw "Compile failed: $name"}
 $objects+=$obj
}
$elf=Join-Path $out 'nh22_udp.elf'
& "$tools\arm-none-eabi-gcc.exe" -mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard -nostartfiles '-Wl,-T' "$root\src\ps\neurohead_ddr_lscript.ld" '-Wl,-e,_vector_table' '-Wl,--gc-sections' -o $elf @objects '-L' "$bsp\lib" '-Wl,--start-group' -llwip4 -lxil -lgcc -lc '-Wl,--end-group'
if($LASTEXITCODE -ne 0){throw 'Link failed'}
& $Python "$root\scripts\inspect_arm_elf.py" $elf --check-startup
if($LASTEXITCODE -ne 0){throw 'ELF startup audit failed'}
& "$tools\arm-none-eabi-objcopy.exe" -O binary -S $elf "$out\nh22_udp.bin"
if($LASTEXITCODE -ne 0){throw 'Objcopy failed'}
& "$tools\arm-none-eabi-size.exe" $elf
Write-Output 'NH22_FIRMWARE_BUILD_PASS (reuses matching PS BSP, no hardware execution)'
