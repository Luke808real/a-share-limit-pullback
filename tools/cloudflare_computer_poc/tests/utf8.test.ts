import { describe, expect, it } from "vitest";
import { truncateUtf8 } from "../src/result";

function utf8Bytes(s: string): number {
  return new TextEncoder().encode(s).byteLength;
}

describe("truncateUtf8 (true UTF-8 byte caps)", () => {
  const samples = {
    ascii: "The quick brown fox jumps over the lazy dog. ".repeat(5),
    chinese: "中文研究文本用于测试截断边界，确保多字节字符不会被拆开。".repeat(3),
    emoji: "a😀b🎉c🚀d🌟e".repeat(5),
    mixed: "R0A 中文 😀 mixed 文本 🎉 tail",
  };

  for (const [name, sample] of Object.entries(samples)) {
    it(`keeps encoded output <= byte limit (${name})`, () => {
      for (const limit of [16, 31, 64, 127, 255, 1000]) {
        const out = truncateUtf8(sample, limit);
        expect(utf8Bytes(out)).toBeLessThanOrEqual(limit);
      }
    });
  }

  it("returns the input unchanged when it fits", () => {
    expect(truncateUtf8("中文😀abc", 1000)).toBe("中文😀abc");
  });

  it("never splits a code point and never introduces U+FFFD", () => {
    const sample = "a😀b中文🎉c";
    for (const limit of [5, 6, 7, 8, 9, 10, 11, 12]) {
      const out = truncateUtf8(sample, limit);
      expect(out).not.toContain("\uFFFD");
      expect(utf8Bytes(out)).toBeLessThanOrEqual(limit);
      // The content prefix must be a valid prefix of the input
      // (ignoring the truncation marker).
      const content = out.replace(/\n\.\.\. \[truncated\]$/, "");
      expect(sample.startsWith(content)).toBe(true);
    }
  });

  it("truncated output is a strict prefix of the input plus the marker", () => {
    const out = truncateUtf8("abcdefghijklmnopqrstuvwxyz0123456789", 20);
    expect(out).toBe("abcd\n... [truncated]");
  });

  it("stays within the limit even when the marker cannot fit", () => {
    for (const limit of [1, 2, 4, 8, 15]) {
      const out = truncateUtf8("abcdefghij中文😀", limit);
      expect(utf8Bytes(out)).toBeLessThanOrEqual(limit);
      expect(out).not.toContain("\uFFFD");
    }
  });
});
