# d2s rollback checkpoint

This checkpoint is mandatory before any One UI 8.5 candidate is flashed. It
records verified recovery inputs; it is not permission to flash the device.

## Stock Odin firmware on the Kubuntu host

Firmware identity:

```text
SM-N975F/BTU
N975FXXS9HWHA/N975FOXM9HWH6/N975FXXS9HWH6
Android 12, bootloader binary 9
```

Samsung's appended MD5 verification passed for every package on 2026-07-18.
The additional host SHA-256 values are:

| Package | Bytes | SHA-256 |
| --- | ---: | --- |
| `AP_N975FXXS9HWHA_CL24230781_QB69546063_REV01_user_low_ship_meta_OS12.tar.md5` | 6,794,670,270 | `406ed7381a6c4015156fcb6354243a6f286efcb16cff36eed892d9b7b35f25f7` |
| `BL_N975FXXS9HWHA_CL24230781_QB69546063_REV01_user_low_ship.tar.md5` | 5,662,897 | `48a70a88a3ed0ec0648155074a38c52be1a1ebbf1e52a54be8482e294b48f45c` |
| `CP_N975FXXS9HWH6_CP24711719_CL24230781_QB68852317_REV01_user_low_ship.tar.md5` | 28,324,029 | `7fac00a64e5657b32099a741635373c51d0d7b1599afee1e95796b4c71aba690` |
| `CSC_OXM_N975FOXM9HWH6_CL24230781_QB68852317_REV01_user_low_ship.tar.md5` | 749,865,144 | `ea425853ea12472468aed269280caae7d025ea15047642b8e762a960b802d6cc` |
| `HOME_CSC_OXM_N975FOXM9HWH6_CL24230781_QB68852317_REV01_user_low_ship.tar.md5` | 749,824,189 | `424a865b769b72074d737e16c433e83a25f965e1d7dc1b2c85a6670438c0f0d8` |

Primary local path:

```text
out/odin/SM-N975F_BTU
```

A byte-for-byte second copy was made on the external backup drive and all
five SHA-256 values above were verified again:

```text
<external-drive-mount>/d2s-rollback-20260718/SM-N975F_BTU
```

Both the primary and Bobo Odin sets were rehashed again on 2026-08-02; all
five files in each set still match the values above.

`HOME_CSC` preserves data only when the partition layout and encryption state
are compatible. It must not be treated as a substitute for a tested backup.
Do not select Odin's repartition option or supply a PIT without first proving
that the current EternityROM layout requires it and that the PIT matches the
exact SM-N975F variant.

## Existing device backups

EFS-family images are stored outside the Git checkout under:

```text
<external-drive-mount>/efs-backup-20260705
```

| Image | Bytes | SHA-256 | Offline check |
| --- | ---: | --- | --- |
| `efs.img` | 20 MiB | `0539cdd5aef3bb9581406660674600b4a7c45bc679c356423bc3af094999cdc8` | `e2fsck -fn` RC 0 |
| `sec_efs.img` | 20 MiB | `54a5fc68bd7b7d2c97a0d06c712e0e783c7f0fe9e0259f27ba22583aef9a4227` | `e2fsck -fn` RC 0 |
| `cpefs.img` | 6 MiB | `9d8a79cd5f1428b987a7d8a2297dc7dcf209a31bdccf72d649b34809aecdb893` | `e2fsck -fn` RC 0 |

Never publish these images. Do not run a modifying filesystem repair against
the only copy; `cpefs.img` legitimately records a recovery-needed journal
flag in the saved snapshot.

A second host-side copy was created on 2026-08-01 at a private, mode `0700`
path outside any Git checkout (not recorded here). All three images are mode
`0600` and their SHA-256 values match the table above.

This protects against losing the Bobo copy, but it is still machine-local and
must remain outside Git and any public artifact upload.

Both protected EFS-family sets were rehashed again on 2026-08-02; all three
images in each set still match the values above.

The phone's removable storage had the following verified items at the last
successful ADB audit:

- known-good `EternityROM_v5.5_d2s.zip`, 5,834,735,912 bytes, SHA-256
  `8830d5d12d01c5987bc292ddeff303dc6cda648e929c338bc1c9259d0ba64834`;
- a roughly 71.5 GiB TWRP backup with all nine critical MD5 sidecars passing;
- TWRP `3.7.1_12-ExtremeXT_v2` recorded in recovery logs.

The phone-side alpha3 ZIP is truncated to 722,506,244 bytes and must never be
flashed. Alpha3 itself is not a known-good rollback ROM because it was never
boot-tested.

## Remaining no-flash gates

- Reconnect the phone and copy the known-good v5.5 ZIP to the host, then
  verify the SHA-256 again.
- With root available, dump the exact installed `recovery` partition
  read-only and hash it; retain a flashable tar/image conversion only after
  its size and header have been verified.
- Re-hash both protected EFS-family copies immediately before flashing.
- Test entry into both recovery and Download Mode without writing a partition.
- Charge to at least 70 percent.
- Obtain explicit approval for the exact candidate SHA-256 before flashing.

Suggested read-only recovery dump after ADB returns:

```bash
adb shell su -c 'blockdev --getsize64 /dev/block/by-name/recovery'
adb exec-out su -c 'dd if=/dev/block/by-name/recovery bs=4M' > recovery-d2s-installed.img
sha256sum recovery-d2s-installed.img
```

Compare the host file size with `blockdev --getsize64`; a matching byte count
and stable repeated SHA-256 are required before using the dump as rollback
material.
