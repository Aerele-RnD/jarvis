import { describe, it, expect } from "vitest"
import { initialsOf } from "./user"

describe("initialsOf", () => {
  it("takes the first letter of the first two words, uppercased", () => {
    expect(initialsOf("Ada Lovelace")).toBe("AL")
    expect(initialsOf("madonna")).toBe("M")
  })
  it("falls back to U for empty/blank", () => {
    expect(initialsOf("")).toBe("U")
    expect(initialsOf("   ")).toBe("U")
    expect(initialsOf(null)).toBe("U")
  })
  it("keeps a whole emoji/astral glyph instead of splitting a surrogate pair", () => {
    // regression for review #13: w[0] would return a lone surrogate half (�)
    expect(initialsOf("🎉 Party")).toBe("🎉P")
    expect(initialsOf("🎉")).toBe("🎉")
  })
})
