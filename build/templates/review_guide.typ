// ============================================================================
// build/templates/review_guide.typ — printable review-guide template.
//
// Wraps generated content with a cover page (title, student, date, coverage
// checklist of the selected knowledge ids) and a table of contents, so every
// generated guide looks like the master document.
//
// build/build.py copies this file next to the generated guide and rewrites
// its lib import to the bundle copy ("lib.typ") because Typst forbids imports
// that escape the project root.
// ============================================================================
#import "../../lib.typ": *

#let review_guide(title: "AP Psychology Review Guide", student: "", ids: (), doc_body) = {
  set document(title: title)
  base_setup(styled_headings({
    align(center)[
      #v(2.2cm)
      #text(size: 21pt, weight: "bold", fill: accent, title)
      #v(0.4cm)
      #if student != "" [#text(size: 12pt)[Prepared for #strong(student)]]
      #v(0.15cm)
      #text(size: 9.5pt, fill: muted, datetime.today().display("[month repr:long] [day], [year]"))
      #v(0.9cm)
      #line(length: 38%, stroke: 1pt + rule_color)
      #v(0.9cm)
      #block(width: 88%)[
        #text(size: 10.5pt, weight: "bold")[Concepts covered: #ids.len()]
        #v(0.35em)
        #grid(
          columns: (1fr, 1fr, 1fr),
          gutter: 10pt,
          ..ids.map(id => align(left)[#text(size: 8.5pt, fill: muted)[( ) #id]])
        )
      ]
    ]
    pagebreak()
    outline(title: [Contents], depth: 2)
    pagebreak()
    doc_body
  }))
}
