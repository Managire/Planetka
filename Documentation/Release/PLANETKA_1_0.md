# Planetka 1.0.0 Editions

Planetka 1.0.0 is a Cinematic Earth Visualistaion System for Blender.

Planetka creates the Earth surface, provides the Planetka Resolve workflow, and streams the required data from Planetka Cloud.

## Editions

Planetka is distributed as separate ZIP files for each edition. They are editions of the same add-on, so installing one edition replaces the other. Only one Planetka edition should be installed at a time.

| Edition | Package | Texture Access | Animation Panel | Licence | Support |
| --- | --- | --- | --- | --- | --- |
| Free | Unsigned ZIP | 1000K textures, capped at d004 or coarser | No | Personal use only | Community support |
| Hobby | Signed ZIP | Full Planetka texture range | No | Personal use only | Community support |
| Pro | Signed ZIP | Full Planetka texture range | No | Commercial use | Direct support, guaranteed data access |
| Studio | Signed ZIP | Full Planetka texture range | Yes: Quick Preview and Final Animation Render | Commercial use, multiple seats | Direct support, guaranteed data access |

Hobby and Pro have identical add-on functionality. They differ by licence, support level, and data-access guarantee. Studio has the same resolving workflow and adds the animation panel.

Edition signatures are used by Planetka Cloud to identify authorised Hobby, Pro, and Studio packages. Free does not require a package signature.

## Licensing And Data

Planetka is distributed under multiple terms. The Blender add-on source code is licensed under the GNU General Public License version 3. Planetka Cloud, hosted texture data, cached texture data, edition signatures, account access, API access, support, service availability, and Planetka's processed texture database are governed by Planetka Terms of Service, Planetka Data Licence, and Fair Usage Policy.

Planetka texture data includes processed and modified derivatives of third-party datasets. Source-data attribution and compliance guidance is included in `Documentation/Licencing/Attribution for User Renders.txt` and `Documentation/Licencing/Compliance/`.

## Fair Usage

Planetka Cloud is a streaming service, not a raw dataset download product.

Data usage per installation is reviewed regularly. If data usage is excessive, Planetka may throttle or block the installation when the activity appears suspicious or consistent with data harvesting.

For unrestricted access, API access to the texture database, or custom arrangements, contact info@planetka.io.

## UI

Planetka has one main panel: `Planetka by Tomas Griger`.

It includes:

- Planetka Data status
- Edition display
- Quality Level: Preview, Balanced, Full
- Combined Create New Earth / Resolve Planetka action
- Tutorials and website links

The Studio edition also includes a second panel for:

- Quick Preview
- Final Animation Render

Free, Hobby, and Pro do not include the animation panel.
