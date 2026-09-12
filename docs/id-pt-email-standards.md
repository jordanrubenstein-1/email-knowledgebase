# Interior Define — Plain Text Email Standards

Standards for building ID plain text (PT) email templates in Braze.

## Greeting
```
Hi {{${first_name} | default: 'there'}},
```
Note: comma after closing brace; default is `'there'` (no exclamation mark).

## From Display Name
```
Rachel from the Interior Define Team
```
Set at the campaign or canvas message step level — not stored in the template.

## Reply-To
```
support@23765919.hubspot-inbox.com
```
Set at the campaign or canvas message step level — not stored in the template.

## Footer
Footer text uses `font-size: 9px`. Format:
```
Copyright © [year], Interior Define, All rights reserved.
3200 Cherry Creek South Drive, Suite 210, Denver, CO 80209

If you would rather not receive future emails from us, you may [unsubscribe].
```
Unsubscribe link: `{{${set_user_to_unsubscribed_url}}}`

## HTML Template Structure
PT emails are still HTML — use a simple table-based layout:
- Container: `width: 600px`, centered
- Body text: `font-family: Arial, sans-serif; font-size: 14px; color: #101b24; line-height: 150%`
- Paragraphs: `<p style="margin: 0 0 14px 0;">`
- Links: `color: #1871D8; text-decoration: underline`
- Footer cell: `font-size: 9px`, same font/color
