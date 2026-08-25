# Derived from claude-config (https://github.com/user/claude-config),
# bin/vimcrypt.py. Implements vim blowfish2 (VimCrypt~03!) decryption.
#
# Decrypt vim "blowfish2" (VimCrypt~03!) files in pure Python.
#
# Implements the decryption side of the "blowfish2" method used by `vim -x`.
# Files are written by vim itself, so only the decryption direction is needed.
# The algorithm is transcribed from vim's src/blowfish.c and src/sha256.c
# (reference copies: ./tmp/plans/ref-vim-blowfish.c and ref-vim-sha256.c) and
# proven byte-exact against real vim in tests.
#
# Layout of a blowfish2 file (all lengths in bytes):
#   "VimCrypt~03!"  (12)  magic
#   salt            (8)
#   seed            (8)
#   ciphertext      (rest)   length == plaintext length (no padding)
#
# Key derivation (vim bf_key_init, 1001 total rounds):
#   sha256(password + salt), then 1000 more rounds of sha256(prev_hex + salt);
#   each round's digest is rendered as lowercase hex and fed back as ASCII
#   bytes. The final 64-hex-char string becomes the 32-byte Blowfish key.
#
# Mode: standard full-block CFB (CFB-64) with the seed as IV. Keystream block
# k = E(C_(k-1)), block 0 = E(seed); C = P XOR keystream; last block unpadded.
#
# The encryption key exists only in the caller's memory: this module never
# writes it to a file, never places it in the environment or a command line,
# never prints it, and never spawns a process for decryption.

import hashlib
import os
import sys

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

VIMCRYPT_MAGIC = b"VimCrypt~03!"
HEADER_LEN = 28  # 12 magic + 8 salt + 8 seed


def _derive_key(password, salt):
    """Return the 32-byte Blowfish key for `password` + `salt`."""
    # Round 1: sha256(password + salt), hex-encoded.
    digest = hashlib.sha256(password.encode("utf-8") + salt).hexdigest()
    # Rounds 2..1001: sha256(prev_hex + salt). The previous digest is fed
    # back as its ASCII hex bytes, matching vim's char_u hex string.
    for _ in range(1000):
        digest = hashlib.sha256(digest.encode("ascii") + salt).hexdigest()
    return bytes.fromhex(digest)


def _swap_words(block8):
    """Reverse the two 4-byte words of an 8-byte block.

    Vim's Blowfish reads each 32-bit word in the file's native little-endian
    byte order (htonl2 is a no-op on little-endian in vim's bf_e_cblock),
    while cryptography's Blowfish reads words big-endian. The round function
    is purely bitwise, so the two agree when every 4-byte word is reversed
    before the cipher and reversed back after. vim's own self-test encodes
    this: the "badcryptxt" entry is exactly what the big-endian reading
    produces. The ECB known-answer vector caught this mismatch during
    implementation.
    """
    return block8[0:4][::-1] + block8[4:8][::-1]


def _bf_ecb(encryptor, block8):
    """vim-compatible Blowfish ECB of one 8-byte block."""
    return _swap_words(encryptor.update(_swap_words(block8)))


def _cfb64_decrypt(key, seed, ciphertext):
    """CFB-64 decrypt of `ciphertext` under a Blowfish ECB key `key`."""
    encryptor = Cipher(algorithms.Blowfish(key), modes.ECB()).encryptor()
    register = seed
    out = bytearray()
    for i in range(0, len(ciphertext), 8):
        block = ciphertext[i : i + 8]
        keystream = _bf_ecb(encryptor, register)
        for j, byte in enumerate(block):
            out.append(byte ^ keystream[j])
        register = block
    return bytes(out)


def decrypt(data, password):
    """Decrypt a vim blowfish2 blob in memory. Returns plaintext bytes.

    Raises ValueError on a missing/unsupported magic, a truncated header, or
    an empty password. A wrong password is not detectable at this layer (the
    format carries no checksum) — it returns garbage bytes; callers detect
    the failure via UTF-8/JSON parsing.
    """
    if not data.startswith(b"VimCrypt~"):
        raise ValueError("not a vim-encrypted file")
    if not data.startswith(VIMCRYPT_MAGIC):
        magic = data[:12].decode("ascii", errors="replace")
        raise ValueError(
            "unsupported vim encryption method " + magic
            + " — only blowfish2 (VimCrypt~03!) is supported"
        )
    if len(data) < HEADER_LEN:
        raise ValueError("truncated or corrupt file (header incomplete)")
    if not password:
        raise ValueError("empty encryption key")
    salt = data[12:20]
    seed = data[20:28]
    ciphertext = data[HEADER_LEN:]
    return _cfb64_decrypt(_derive_key(password, salt), seed, ciphertext)


# ── hidden input ──────────────────────────────────────────────────────


def _write_terminal(text):
    """Write prompt/echo text straight to the user's terminal.

    Bypasses fd 1/2 entirely — those may be redirected into the scanner's
    protocol pipe (set-llm-keys) or a file. Windows opens the console output
    buffer directly (CONOUT$): GetStdHandle returns the redirected pipe, not
    the console, when stderr is piped. Unix opens /dev/tty. Falls back to
    stderr when no console/tty is reachable (CI, CREATE_NO_CONSOLE children),
    keeping automation deterministic. Never writes password content; never
    raises.
    """
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateFileW.restype = ctypes.c_void_p
        kernel32.CreateFileW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        kernel32.WriteConsoleW.restype = ctypes.c_uint32
        kernel32.WriteConsoleW.argtypes = [
            ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        FILE_SHARE_READ = 0x1
        FILE_SHARE_WRITE = 0x2
        OPEN_EXISTING = 3
        try:
            conout = kernel32.CreateFileW(
                "CONOUT$", GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None, OPEN_EXISTING, 0, None)
            if conout not in (None, 0, ctypes.c_void_p(-1).value):
                try:
                    written = ctypes.c_uint32()
                    if kernel32.WriteConsoleW(
                            conout, text, len(text),
                            ctypes.byref(written), None):
                        return
                finally:
                    kernel32.CloseHandle(conout)
        except Exception:
            pass
        sys.stderr.write(text)
        sys.stderr.flush()
        return
    _data = text.encode('utf-8', 'replace')
    # Try 1: os.ttyname(0) — the real device path (e.g. /dev/ttys003 on
    # macOS, /dev/pts/N on Linux). Works in contexts where the /dev/tty
    # alias fails (e.g. ENXIO when the process has no controlling terminal
    # but fd 0 is still the tty, as in a shell process substitution).
    try:
        _tty_path = os.ttyname(0)
        if _tty_path:
            _fd = os.open(_tty_path, os.O_WRONLY)
            try:
                os.write(_fd, _data)
            finally:
                os.close(_fd)
            return
    except Exception:
        pass
    # Try 2: /dev/tty — the standard controlling-terminal alias.
    try:
        with open("/dev/tty", "w") as tty:
            tty.write(text)
            tty.flush()
        return
    except Exception:
        pass
    # Try 3: write directly to stdin's fd (bidirectional on Unix).
    try:
        if os.isatty(0):
            os.write(0, _data)
            return
    except Exception:
        pass
    sys.stderr.write(text)
    sys.stderr.flush()


def _read_password_windows(prompt):
    """Read a secret from the Windows console with echo disabled.

    Returns None when no console is attached (bare mintty without winpty,
    ssh, CI, CREATE_NO_CONSOLE children) so the caller can fall back to the
    stdin path. Uses msvcrt.getwch() (wide chars — Chinese keys work) with
    echo cleared via SetConsoleMode; follows the bin/claude_utils.py
    `_read_password_windows` loop shape.
    """
    import ctypes
    import msvcrt

    kernel32 = ctypes.windll.kernel32
    kernel32.GetStdHandle.restype = ctypes.c_void_p
    kernel32.GetStdHandle.argtypes = [ctypes.c_int]
    kernel32.GetConsoleMode.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel32.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.GetConsoleWindow.restype = ctypes.c_void_p

    ENABLE_ECHO_INPUT = 0x0004
    handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
    mode = ctypes.c_uint32()
    stdin_is_console = bool(kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    console_attached = bool(kernel32.GetConsoleWindow())
    if not (stdin_is_console or console_attached):
        return None
    restore_mode = None
    try:
        if stdin_is_console:
            new_mode = mode.value & ~ENABLE_ECHO_INPUT
            if kernel32.SetConsoleMode(handle, new_mode):
                restore_mode = mode.value
        # Stream discipline: the prompt, stars, backspaces, and terminating
        # newline go directly to the terminal via _write_terminal (CONOUT$)
        # with a stderr fallback — visible even when stdout/stderr are
        # redirected into the scanner's protocol pipe or a file.
        _write_terminal(prompt)
        password = ""
        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                _write_terminal("\n")
                break
            elif ch == "\x03":
                raise KeyboardInterrupt
            elif ch in ("\x08", "\x7f"):
                if password:
                    password = password[:-1]
                    _write_terminal("\b \b")
            else:
                password += ch
                _write_terminal("*")
        if not password:
            raise ValueError("empty encryption key")
        return password
    finally:
        if restore_mode is not None:
            kernel32.SetConsoleMode(handle, restore_mode)


def _read_password_unix(prompt):
    """Read a secret from a Unix tty with echo off and a '*' per char.

    Called only when stdin is a tty AND this process is in the terminal's
    foreground process group (prompt_hidden checks). That precondition
    matters: a BACKGROUND process group is stopped by the kernel (SIGTTIN
    on reads, SIGTTOU on mode changes) the instant it touches the terminal
    — an indefinite silent freeze that no in-process timeout can break
    (this bit us inside zsh/bash process substitution, where the scanner
    runs in its own background pgrp). Foreground processes are unaffected:
    tcsetattr here is an ordinary, instant call.
    """
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        _write_terminal(prompt)
        password = ""
        while True:
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                _write_terminal("\n")
                break
            elif ch == "\x03":
                raise KeyboardInterrupt
            elif ch == "":
                # tty closed mid-prompt (Ctrl-D under cbreak is a literal
                # byte, not EOF).
                raise ValueError("empty encryption key")
            elif ch in ("\x7f", "\x08"):
                if password:
                    password = password[:-1]
                    _write_terminal("\b \b")
            else:
                password += ch
                _write_terminal("*")
        if not password:
            raise ValueError("empty encryption key")
        return password
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def prompt_hidden(prompt):
    """Read a secret from the user without echoing it. Returns the string.

    Dispatch order (the key is never written to any stream):
      1. Windows (tty or pipe stdin): attempt the console read with echo
         disabled — a console exists under Windows Terminal / conhost / winpty
         even when stdin is a pipe. When NO console is attached the read
         returns None and we fall through to (3) — never return None, not even
         from the tty branch (bare mintty + msys2 python is a tty with no
         Win32 console; review R1).
      2. Unix, stdin is a tty AND this process is in the terminal's
         foreground process group -> termios read on stdin with echo off.
         A background pgrp (e.g. inside a shell process substitution) is
         stopped by the kernel on any terminal op — refused with ValueError
         up front instead of freezing forever; wrappers pipe the key on
         stdin (path 3) in that case.
      3. stdin line read (tests/automation/headless), announced directly to
         the terminal via _write_terminal, one trailing CR and LF stripped
         (CRLF-safe); empty line/EOF -> ValueError.
      4. getpass.getpass as a final safety net.
    """
    try:
        is_tty = sys.stdin.isatty()
    except Exception:
        is_tty = False

    if os.name == "nt":
        console_result = _read_password_windows(prompt)
        if console_result is not None:
            return console_result
    elif is_tty:
        try:
            fg_pgrp = os.tcgetpgrp(sys.stdin.fileno())
        except OSError:
            fg_pgrp = None
        if fg_pgrp is not None and fg_pgrp != os.getpgrp():
            raise ValueError(
                "cannot prompt for the key interactively — this process is "
                "in a background process group (terminal reads would be "
                "stopped by the kernel); pipe the key on stdin instead")
        return _read_password_unix(prompt)

    # stdin line read for tests/automation/headless
    _write_terminal("reading encryption key from stdin (non-interactive)\n")
    try:
        line = sys.stdin.readline()
    except Exception:
        import getpass
        password = getpass.getpass(prompt)
        if not password:
            raise ValueError("empty encryption key")
        return password
    if line == "":
        raise ValueError("empty encryption key")
    line = line.rstrip("\r\n")
    if line == "":
        raise ValueError("empty encryption key")
    return line


# ── self test ─────────────────────────────────────────────────────────

# Multi-block CFB known-answer vector generated during implementation from
# the real vim (9.1, blowfish2): `vim -n -x` on a 16-byte plaintext with a
# fixed key. The header (salt/seed) was captured from the produced file and
# the ciphertext recorded as a constant. This exercises the CFB chaining,
# which the single ECB vector below cannot.
CFB_TEST_PASSWORD = "testkey"
CFB_TEST_PLAINTEXT = b"0123456789abcdef"
CFB_TEST_SALT = bytes.fromhex("84e491d5f1c66941")
CFB_TEST_SEED = bytes.fromhex("962165855a83cadd")
CFB_TEST_CIPHERTEXT = bytes.fromhex("e52f226f0d5706ddd2b55e6cd99b4c33")


def _self_test():
    """Run the known-answer vectors. Returns True when all pass."""
    # (a) The single portable ECB vector from vim's bf_test_data:
    #     password "password", salt "salt" -> encrypt "plaintxt".
    key = _derive_key("password", b"salt")
    encryptor = Cipher(algorithms.Blowfish(key), modes.ECB()).encryptor()
    if _bf_ecb(encryptor, b"plaintxt") != bytes.fromhex("ad3dfa7fe8ea40f6"):
        return False

    # (b) Multi-block CFB known-answer vector from real vim.
    plain = _cfb64_decrypt(
        _derive_key(CFB_TEST_PASSWORD, CFB_TEST_SALT),
        CFB_TEST_SEED,
        CFB_TEST_CIPHERTEXT,
    )
    return plain == CFB_TEST_PLAINTEXT


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        ok = _self_test()
        print("vimcrypt self-test " + ("PASS" if ok else "FAIL"))
        sys.exit(0 if ok else 1)
    print("usage: python vimcrypt.py --self-test", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
