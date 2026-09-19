const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        AlignmentType, HeadingLevel, BorderStyle, WidthType, ShadingType,
        VerticalAlign } = require('docx');
const fs = require('fs');

// ─────────────────────────────────────────────────────────────────────────────
// Copy data
// ─────────────────────────────────────────────────────────────────────────────

const EMAILS = [
  {
    collection: 'Sloan',
    eyebrow: 'THE SLOAN COLLECTION',
    headline: 'You chose well. Now meet the rest of the family.',
    intro: 'The Sloan collection is built to grow with your space — every piece made to order in the same fabric, the same finish, and the same exacting detail as the sofa on its way to you.',
    products: [
      {
        label: 'SLOAN SLEEPER',
        tagline: 'The room that does it all.',
        body: 'Same Sloan silhouette, queen bed inside. For the guest room that refuses to look like one.',
        cta: 'Shop the Sloan Sleeper →',
      },
      {
        label: 'SLOAN LEATHER',
        tagline: 'A different material. The same timeless lines.',
        body: 'The Sloan in leather — rich, considered, and built to last decades.',
        cta: 'Shop Sloan Leather →',
      },
      {
        label: 'SLOAN OTTOMAN',
        tagline: 'The piece that brings it together.',
        body: 'Built to match your sofa down to the fabric and finish. Use it as a footrest or an extra seat.',
        cta: 'Shop the Sloan Ottoman →',
      },
      {
        label: 'SLOAN CHAISE',
        tagline: 'More room to stretch out.',
        body: 'The Sloan chaise lounge in your fabric and finish — a longer seat for reading, lounging, or anchoring the other end of the room.',
        cta: 'Shop the Sloan Chaise →',
      },
    ],
    ctaBar: 'See everything Sloan →',
  },
  {
    collection: 'James',
    eyebrow: 'THE JAMES COLLECTION',
    headline: 'You chose well. Now meet the rest of the family.',
    intro: 'The James collection is built to grow with your space — every piece made to order in the same fabric and the same exacting detail as the sofa on its way to you.',
    products: [
      {
        label: 'JAMES SLEEPER',
        tagline: 'The room that does it all.',
        body: 'Same James silhouette, queen bed inside. For the guest room that refuses to look like one.',
        cta: 'Shop the James Sleeper →',
      },
      {
        label: 'JAMES LEATHER',
        tagline: 'A different material. The same timeless lines.',
        body: 'The James in leather — rich, considered, and built to last decades.',
        cta: 'Shop James Leather →',
      },
      {
        label: 'JAMES TWIN SLEEPER',
        tagline: 'Your guest room, solved.',
        body: 'The James with a pull-out twin inside — for the room that needs to be two things at once. Same silhouette, made to order in your fabric.',
        cta: 'Shop the James Twin Sleeper →',
      },
      {
        label: 'JAMES OTTOMAN',
        tagline: 'The piece that brings it together.',
        body: 'Built to match your sofa fabric. Storage inside, style outside.',
        cta: 'Shop the James Ottoman →',
      },
    ],
    ctaBar: 'See everything James →',
  },
  {
    collection: 'Maxwell',
    eyebrow: 'THE MAXWELL COLLECTION',
    headline: 'You chose well. Now meet the rest of the family.',
    intro: 'The Maxwell collection is built to grow with your space — every piece made to order in the same fabric, the same finish, and the same exacting detail as the sofa on its way to you.',
    products: [
      {
        label: 'MAXWELL TALL',
        tagline: 'A higher seat changes everything.',
        body: 'The Tall Maxwell sits at an 18” seat height versus the standard 16” — easier to sit down, easier to get up, and a noticeably different proportion for taller rooms or taller people.',
        cta: 'Shop the Maxwell Tall →',
      },
      {
        label: 'MAXWELL SLIPCOVERED',
        tagline: 'The same Maxwell. A softer look.',
        body: 'The Maxwell in a slipcover finish — a more relaxed, casual silhouette. Made to order in your fabric.',
        cta: 'Shop Maxwell Slipcovered →',
      },
      {
        label: 'MAXWELL LEATHER',
        tagline: 'A different material. The same timeless lines.',
        body: 'The Maxwell in leather — rich, considered, and built to last decades.',
        cta: 'Shop Maxwell Leather →',
      },
      {
        label: 'MAXWELL OTTOMAN',
        tagline: 'The piece that brings it together.',
        body: 'Built to match your sofa down to the fabric and finish. Use it as a footrest or an extra seat.',
        cta: 'Shop the Maxwell Ottoman →',
      },
    ],
    ctaBar: 'See everything Maxwell →',
  },
];

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

const CONTENT_WIDTH = 9360; // 8.5" page, 1" margins each side
const COL_HALF = 4680;
const GRAY = 'AAAAAA';
const DARK = '101b24';
const MID = '555555';
const RULE_COLOR = 'E6E6E6';

function rule() {
  return new Paragraph({
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: RULE_COLOR, space: 0 } },
    spacing: { before: 0, after: 0 },
    children: [],
  });
}

function spacer(pts = 120) {
  return new Paragraph({ spacing: { before: pts, after: 0 }, children: [] });
}

function productTable(products) {
  const cellBorder = { style: BorderStyle.SINGLE, size: 4, color: RULE_COLOR };
  const borders = { top: cellBorder, bottom: cellBorder, left: cellBorder, right: cellBorder };

  function makeCell(p) {
    return new TableCell({
      width: { size: COL_HALF, type: WidthType.DXA },
      borders,
      margins: { top: 160, bottom: 200, left: 200, right: 200 },
      verticalAlign: VerticalAlign.TOP,
      children: [
        new Paragraph({
          spacing: { before: 0, after: 80 },
          children: [new TextRun({ text: p.label, font: 'Arial', size: 16, bold: true, color: GRAY, allCaps: true })],
        }),
        new Paragraph({
          spacing: { before: 0, after: 100 },
          children: [new TextRun({ text: p.tagline, font: 'Georgia', size: 24, bold: true, italics: true, color: DARK })],
        }),
        new Paragraph({
          spacing: { before: 0, after: 140 },
          children: [new TextRun({ text: p.body, font: 'Arial', size: 22, color: MID })],
        }),
        new Paragraph({
          spacing: { before: 0, after: 0 },
          children: [new TextRun({ text: p.cta, font: 'Arial', size: 22, color: '1871D8' })],
        }),
      ],
    });
  }

  const rows = [];
  for (let i = 0; i < products.length; i += 2) {
    rows.push(new TableRow({
      children: [makeCell(products[i]), makeCell(products[i + 1])],
    }));
  }

  return new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [COL_HALF, COL_HALF],
    rows,
  });
}

function emailSection(email, isFirst) {
  const children = [];

  if (!isFirst) {
    children.push(new Paragraph({ children: [new TextRun({ break: 1 })], spacing: { before: 0, after: 0 } }));
  }

  // Collection header
  children.push(new Paragraph({
    heading: HeadingLevel.HEADING_1,
    children: [new TextRun({ text: `Email ${['Sloan','James','Maxwell'].indexOf(email.collection) + 1}: ${email.collection} Variant`, font: 'Arial', size: 36, bold: true, color: DARK })],
    spacing: { before: isFirst ? 0 : 480, after: 240 },
  }));

  children.push(rule());
  children.push(spacer(200));

  // Subject/Preheader note
  children.push(new Paragraph({
    spacing: { before: 0, after: 80 },
    children: [new TextRun({ text: 'Subject / Preheader:', font: 'Arial', size: 22, bold: true, color: DARK })],
  }));
  children.push(new Paragraph({
    spacing: { before: 0, after: 240 },
    children: [new TextRun({ text: '[To be set in canvas — not yet defined]', font: 'Arial', size: 22, color: GRAY, italics: true })],
  }));

  // Eyebrow
  children.push(new Paragraph({
    spacing: { before: 0, after: 80 },
    children: [new TextRun({ text: 'Eyebrow', font: 'Arial', size: 22, bold: true, color: DARK })],
  }));
  children.push(new Paragraph({
    spacing: { before: 0, after: 240 },
    children: [new TextRun({ text: email.eyebrow, font: 'Arial', size: 22, color: MID, allCaps: true })],
  }));

  // Headline
  children.push(new Paragraph({
    spacing: { before: 0, after: 80 },
    children: [new TextRun({ text: 'Headline', font: 'Arial', size: 22, bold: true, color: DARK })],
  }));
  children.push(new Paragraph({
    spacing: { before: 0, after: 240 },
    children: [new TextRun({ text: email.headline, font: 'Arial', size: 22, color: MID })],
  }));

  // Intro
  children.push(new Paragraph({
    spacing: { before: 0, after: 80 },
    children: [new TextRun({ text: 'Intro Copy', font: 'Arial', size: 22, bold: true, color: DARK })],
  }));
  children.push(new Paragraph({
    spacing: { before: 0, after: 320 },
    children: [new TextRun({ text: email.intro, font: 'Arial', size: 22, color: MID })],
  }));

  // Product grid label
  children.push(new Paragraph({
    spacing: { before: 0, after: 120 },
    children: [new TextRun({ text: 'Product Grid (2×2)', font: 'Arial', size: 22, bold: true, color: DARK })],
  }));

  // Product grid table
  children.push(productTable(email.products));
  children.push(spacer(200));

  // CTA bar
  children.push(new Paragraph({
    spacing: { before: 0, after: 80 },
    children: [new TextRun({ text: 'Bottom CTA Bar', font: 'Arial', size: 22, bold: true, color: DARK })],
  }));
  children.push(new Paragraph({
    spacing: { before: 0, after: 0 },
    children: [new TextRun({ text: email.ctaBar, font: 'Arial', size: 22, color: MID })],
  }));

  return children;
}

// ─────────────────────────────────────────────────────────────────────────────
// Document
// ─────────────────────────────────────────────────────────────────────────────

const allChildren = [];

// Title
allChildren.push(new Paragraph({
  heading: HeadingLevel.HEADING_1,
  children: [new TextRun({ text: 'ID Post-Purchase Sofa — Email Copy', font: 'Arial', size: 44, bold: true, color: DARK })],
  spacing: { before: 0, after: 120 },
}));
allChildren.push(new Paragraph({
  spacing: { before: 0, after: 60 },
  children: [new TextRun({ text: 'Interior Define • Post Purchase — Sofa Canvas', font: 'Arial', size: 22, color: GRAY })],
}));
allChildren.push(new Paragraph({
  spacing: { before: 0, after: 60 },
  children: [new TextRun({ text: 'One dynamic email, three collection variants. Triggered on sofa purchase via Order Completed event.', font: 'Arial', size: 22, color: MID, italics: true })],
}));
allChildren.push(new Paragraph({
  spacing: { before: 0, after: 400 },
  children: [new TextRun({ text: 'Shared footer across all variants:', font: 'Arial', size: 22, color: DARK, bold: true }), new TextRun({ text: ' © Interior Define • 3200 Cherry Creek South Drive, Suite 210, Denver, CO 80209 + Unsubscribe link', font: 'Arial', size: 22, color: MID })],
}));
allChildren.push(rule());

// Email sections
EMAILS.forEach((email, i) => {
  emailSection(email, i === 0).forEach(c => allChildren.push(c));
  if (i < EMAILS.length - 1) {
    allChildren.push(spacer(80));
    allChildren.push(rule());
  }
});

const doc = new Document({
  styles: {
    default: { document: { run: { font: 'Arial', size: 24 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 36, bold: true, font: 'Arial' },
        paragraph: { spacing: { before: 240, after: 180 }, outlineLevel: 0 } },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
      },
    },
    children: allChildren,
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync('/Users/jordan.rubenstein/Downloads/ID_PostPurchase_Sofa_Copy.docx', buf);
  console.log('Done: /Users/jordan.rubenstein/Downloads/ID_PostPurchase_Sofa_Copy.docx');
});
