/**
 * Clean PDF-extracted chunk text for readable display.
 * ArXiv PDFs often dump broken math as variation selectors + random operators.
 */

function mapMathAlphanumeric(code: number): string | null {
  const ranges: Array<[number, number, number]> = [
    [0x1d400, 0x1d419, 65],
    [0x1d41a, 0x1d433, 97],
    [0x1d434, 0x1d44d, 65],
    [0x1d44e, 0x1d467, 97],
    [0x1d468, 0x1d481, 65],
    [0x1d482, 0x1d49b, 97],
    [0x1d49c, 0x1d4b5, 65],
    [0x1d4d0, 0x1d4e9, 65],
    [0x1d4ea, 0x1d503, 97],
    [0x1d504, 0x1d51d, 65],
    [0x1d51e, 0x1d537, 97],
    [0x1d538, 0x1d551, 65],
    [0x1d552, 0x1d56b, 97],
    [0x1d56c, 0x1d585, 65],
    [0x1d586, 0x1d59f, 97],
    [0x1d5a0, 0x1d5b9, 65],
    [0x1d5ba, 0x1d5d3, 97],
    [0x1d5d4, 0x1d5ed, 65],
    [0x1d5ee, 0x1d607, 97],
    [0x1d608, 0x1d621, 65],
    [0x1d622, 0x1d63b, 97],
    [0x1d63c, 0x1d655, 65],
    [0x1d656, 0x1d66f, 97],
    [0x1d670, 0x1d689, 65],
    [0x1d68a, 0x1d6a3, 97],
    [0x1d7ce, 0x1d7d7, 48],
    [0x1d7d8, 0x1d7e1, 48],
    [0x1d7e2, 0x1d7eb, 48],
    [0x1d7ec, 0x1d7f5, 48],
    [0x1d7f6, 0x1d7ff, 48],
  ]
  for (const [start, end, base] of ranges) {
    if (code >= start && code <= end) {
      return String.fromCharCode(base + (code - start))
    }
  }
  const singles: Record<number, string> = {
    0x210e: 'h',
    0x2102: 'C',
    0x210d: 'H',
    0x2115: 'N',
    0x2119: 'P',
    0x211a: 'Q',
    0x211d: 'R',
    0x2124: 'Z',
  }
  return singles[code] ?? null
}

function isVariationSelector(code: number): boolean {
  return (
    (code >= 0xfe00 && code <= 0xfe0f) ||
    (code >= 0xe0100 && code <= 0xe01ef)
  )
}

function isCombining(code: number): boolean {
  return (
    (code >= 0x0300 && code <= 0x036f) ||
    (code >= 0x1ab0 && code <= 0x1aff) ||
    (code >= 0x1dc0 && code <= 0x1dff) ||
    (code >= 0x20d0 && code <= 0x20ff) ||
    (code >= 0xfe20 && code <= 0xfe2f)
  )
}

/** PDF math-dump glyphs that rarely appear in prose. */
function isBrokenMathGlyph(code: number): boolean {
  if (code >= 0x2200 && code <= 0x22ff) return true
  if (code >= 0x2300 && code <= 0x23ff) return true
  if (code >= 0x27c0 && code <= 0x27ef) return true
  if (code >= 0x2980 && code <= 0x29ff) return true
  if (code >= 0x2a00 && code <= 0x2aff) return true
  if (code >= 0x1d6a4 && code <= 0x1d7c3) return true
  return false
}

/** True when chars[j] starts a normal word like "Most", not a lone math var "Q". */
function startsProseWord(chars: string[], j: number): boolean {
  if (j >= chars.length || !/[A-Za-z\u4e00-\u9fff]/.test(chars[j])) return false
  if (/[\u4e00-\u9fff]/.test(chars[j])) return true
  const next = chars[j + 1]
  return Boolean(next && /[a-z]/.test(next))
}

function replaceBrokenFormulaRuns(text: string): string {
  const chars = [...text]
  let out = ''
  let i = 0
  while (i < chars.length) {
    const code = chars[i].codePointAt(0)!
    const startsJunk =
      isBrokenMathGlyph(code) || chars[i] === '{' || chars[i] === '}'
    if (!startsJunk) {
      out += chars[i]
      i += 1
      continue
    }

    const before = out.match(/([A-Za-z]\s*=\s*[A-Za-z]?)\s*$/)
    let head = ''
    if (before) {
      head = before[1].replace(/\s+/g, '')
      out = out.slice(0, out.length - before[0].length)
    }

    let j = i
    let glyphCount = 0
    const varList: string[] = []
    while (j < chars.length) {
      if (startsProseWord(chars, j) && glyphCount >= 2) break
      const c = chars[j]
      const o = c.codePointAt(0)!
      const isJunk =
        isBrokenMathGlyph(o) ||
        '{}[]().,\\/|=_+*^~<>'.includes(c) ||
        /\s/.test(c)
      const isVar = /^[A-Za-z]$/.test(c)
      if (!isJunk && !isVar) break
      if (isBrokenMathGlyph(o)) glyphCount += 1
      if (isVar) varList.push(c)
      j += 1
      if (j - i > 100) break
    }

    if (glyphCount >= 2) {
      // drop trailing punctuation absorbed into the run
      while (j > i && /[.\s]/.test(chars[j - 1])) j -= 1
      const vars = [...new Set(varList)].join(', ')
      if (head && vars) {
        const fn = head.length >= 3 ? head.slice(2) : 'f'
        out += `${head[0]} = ${fn}(${vars})`
      } else if (head) {
        out += `${head[0]} = ${head.slice(2) || 'f'}(·)`
      } else {
        out += '〔公式〕'
      }
      i = j
      continue
    }

    out += chars[i]
    i += 1
  }
  return out
}

function tidyProse(text: string): string {
  return text
    .replace(/^\s*[.·•]\s+/, '')
    .replace(/(\p{L})-\s+(\p{L})/gu, '$1$2')
    .replace(/([a-z\u4e00-\u9fff])([A-Z])(?=[^a-z]|$)/g, '$1 $2')
    .replace(/([.:;,])([A-Za-z])/g, '$1 $2')
    .replace(/([a-z])([A-Z][a-z])/g, '$1 $2')
    // glued compounds from PDF: phrasespre-processing → phrases pre-processing
    .replace(/([a-z])((?:pre|post|non|multi|sub|co)-[a-z])/gi, '$1 $2')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/\s+([,.;:!?])/g, '$1')
    .replace(/(〔公式〕\s*)+/g, '〔公式〕')
    .replace(/\s*〔公式〕\s*/g, ' 〔公式〕 ')
    .replace(/[ \t]{2,}/g, ' ')
    .trim()
}

export function formatChunkText(raw: string | null | undefined): string {
  if (!raw) return ''
  let text = raw.normalize('NFKC')

  let out = ''
  for (const ch of text) {
    const code = ch.codePointAt(0)!
    if (isVariationSelector(code) || isCombining(code)) continue
    const mapped = mapMathAlphanumeric(code)
    if (mapped !== null) {
      out += mapped
      continue
    }
    if (
      (code < 32 && code !== 9 && code !== 10 && code !== 13) ||
      code === 0xfffd ||
      (code >= 0xe000 && code <= 0xf8ff) ||
      (code >= 0xf0000 && code <= 0xffffd)
    ) {
      continue
    }
    out += ch
  }

  out = replaceBrokenFormulaRuns(out)
  return tidyProse(out)
}
