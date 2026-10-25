from __future__ import annotations
import re
import sys
from pathlib import Path
BRIEF_CUT_ANCHORS = ('Join Now', 'API licensing', 'Make us preferred', 'Sign In', 'Sign Up', 'Create Free Account', 'Create Account', 'INVEST NOW', 'Invest Now', 'Access Chart Alerts', 'Faster Updating Charts', 'Tradingview Indicators', 'Need this data in your product', 'Documentation Copy page', 'Open Our ETFs', 'Our ETFs Open', 'Skip to content', 'Skip to main content', 'Original Article', 'Make us preferred on Google', 'Subscribe Now', 'Log In', 'Start Free', 'Get Started', 'View PDF', 'Focus to learn more', 'Show source table', 'Image Source', 'Learn More', 'Watch Now')
LEVEL_RE = re.compile('^\\s*(?:\\*\\*)?\\s*(?:eli5|undergrad|grad|phd|implementation)\\b[^\\n]*$', re.I)
EXEC_RE = re.compile('^\\s*(?:>\\s*)?\\*\\*(?:Executive Brief|ELI5|Undergrad|Grad|PhD|Implementation)(?:[^*]*)?\\*\\*', re.I)

def _nav_line(s: str) -> bool:
    t = s.strip()
    if not 4 <= len(t) <= 90:
        return False
    if re.match('^[#>|!]|^\\s*[-*+] |^\\s*\\d+\\.\\s', t):
        return False
    if t.endswith(('.', '!', '?', ';', ':', ')')) and ':' not in t[:-1]:
        return False
    if re.search('\\[[^\\]]+\\]\\(', t) or re.match('^https?://', t):
        return True
    if re.match('^[A-Z0-9¢₿$\'\\"“ \\-–—/&,:%().+]+$', t) and (not re.search('\\b(\\w+ing|\\w+ed)\\b', t)):
        return False
    return True
JUNK_LINE_RE = re.compile('^(\\s*)(©|copyright\\b|all rights reserved|loading\\s*\\.*$|powered by\\b|make us preferred\\b|zoom in with\\b|zoom in on\\b|reset: double click|need this data in your product|access chart alerts|faster updating charts|private tradingview indicators|insight reports|subscription term|current plan|upgrade\\b|log in$|sign in$|sign up$|create free account$|newsletter\\b|skip to (main )?content$|original article$|image source$|view pdf$|view pdf html|focus to learn more$|learn more$|cancel anytime|about us\\b|advertise\\b|cookie policy|privacy policy|terms of (use|service)|editorial process|careers$|contact us$|follow us\\b|investing simulator|banking$|personal finance$|economy$|reviews$|dictionary$|skip to main|what is (the |connected |litmaps |alphaxiv |dagshub |gotitpub |huggingface )|what are (smart citations|influence flowers|mathjax)?|bibliographic (and |explorer |tools)|literature and citation|export bibtex|cite as\\b|submission history|current browse context|< prev|next >|new \\| recent|report issue|member institutions|research conducted for educational|simons foundation|\\d+ (free|free ) bitcoin charts|100\\+ free bitcoin charts|your view of this chart is limited|subscribe here\\.?$|view the (bitcoin )?fear ?\\&? ?greed|charts\\.bitbo\\.io$|bitbo news$|free basic charts|macro suite|portfolio tools|complete access|alerts —|alerts\\b ?—|downloadable data|university suite|api licensing|\\[?skip to main content\\]?\\(.*\\)|^top picks?$|^buy btc\\b|best sites to buy|mcp ask your|terminal every btc|unlock \\d+\\+? private charts|make.{0,12}google|original article)', re.I)
URL_RE = re.compile('https?://\\S+')
NESTED_LINK_IN_ANCHOR_RE = re.compile('(?<!\\!)\\[[^\\]]{0,300}\\n-?\\s*\\[[^\\]]{1,40}\\][^\\]]{0,800}\\]\\(https?://[^)]+\\)')

def _only_url(s: str) -> bool:
    t = URL_RE.sub('', s)
    return len(re.sub('[\\s\\|\\-\\(\\)\\[\\]\\.>,•*~`#]', '', t)) <= 16
JUNK_IMG_RE = re.compile('!\\[\\s*([^\\]]*?)(screenshot|screen shot|banner|nav|menu|subscribe|logo|powered by|buy now|join now|free trial|get started|promo)[^\\]]*\\]?\\(', re.I)
JUNK_IMG_URL_RE = re.compile('https?://[^)]*(?:/icons?/|/img/icons/|_1px\\.|favicon|sprite|placeholder|/buttons?/|/banners?/|loading|spinner|tracking|pixel\\.|1x1|default[_-]?(image|img|avatar|profile|user|thumb))', re.I)
SCHEME_RE = re.compile('(?i)^[a-z][a-z0-9+.\\-]+://')
IMG_SRC_RE = re.compile('!\\[[^\\]]*\\]\\(([^)\\s]+)(?:\\s+\\"[^\\"]*\\")?\\)')
_CREDIT_OPEN_RE = re.compile('^\\*Image:')
_CREDIT_CLOSE_RE = re.compile('\\*\\s*$')
_MD_STRUCT_RE = re.compile('^(?:#|\\||!\\[|[-+] |\\d+\\. |```|>)')

def _img_src_of(ln: str) -> str | None:
    m = IMG_SRC_RE.search(ln)
    return m.group(1) if m else None

def _drop_paired_credit(lines: list, img_idx: int) -> int:
    n = len(lines)
    i = img_idx + 1
    while i < n and (not lines[i].strip()):
        i += 1
    if i >= n or not _CREDIT_OPEN_RE.match(lines[i].strip()):
        return img_idx
    blk = i
    stop = min(n, i + 15)
    j = i
    while j < stop and (not _MD_STRUCT_RE.match(lines[j].strip())):
        j += 1
        if _CREDIT_CLOSE_RE.search(lines[j - 1].strip()):
            del lines[blk:j]
            return blk
    return img_idx

def _is_local_img_line(ln: str) -> bool:
    src = _img_src_of(ln)
    return bool(src) and (not SCHEME_RE.match(src))
PROTECT_HEAD_RE = re.compile('^\\s*##?\\s*(?:\\d*\\.?\\s*)?(primary sources|related research|sources\\b)', re.I)
KEEP_URL_SECTION_RE = re.compile('(?i)^\\s*(?:#+\\s*)?(?:\\d+(?:\\.\\d+)?\\.?\\s+)?(?:primary sources|sources|references|citations)\\b[^\\n]{0,60}$')
DROP_SECTION_RE = re.compile('^\\s*##?\\s*(?:\\d*\\.?\\s*)?(primary sources|related research|sources\\b|references\\b|citations\\b|external links\\b|further reading\\b|see also\\b|bibliography\\b)', re.I)
PROSE_UNWRAP_HOST_RE = re.compile('https?://(?:www\\.)?(?:personiq\\.io|tracerfy\\.com|proptream\\.com|batchleads\\.com|skipgenie\\.com|thatsthem\\.com|beenverified\\.com|spokeo\\.com|intelius\\.com|truthfinder\\.com|whitepages\\.com|fastpeoplesearch\\.com|peekyou\\.com|pipl\\.com|linkedin\\.com|facebook\\.com|twitter\\.com|x\\.com|instagram\\.com|reddit\\.com|youtube\\.com|tiktok\\.com|pinterest\\.com)\\b', re.I)
H2_H3_RE = re.compile('^\\s*##+ ')
TABLE_RE = re.compile('^\\s*\\|')
FENCE_RE = re.compile('^\\s*```')

def _protect_keep_sections(md_text: str) -> tuple[str, list[tuple[str, str]]]:
    lines = md_text.split('\n')
    out: list[str] = []
    blocks: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        if KEEP_URL_SECTION_RE.match(lines[i].strip()):
            j, fence = (i + 1, False)
            while j < len(lines):
                if FENCE_RE.match(lines[j]):
                    fence = not fence
                elif not fence and H2_H3_RE.match(lines[j]):
                    break
                j += 1
            block = '\n'.join(lines[i:j])
            placeholder = f'#KEEP-URL-SECTION-{len(blocks)}#'
            blocks.append((placeholder, block))
            out.append(placeholder)
            i = j
            continue
        out.append(lines[i])
        i += 1
    return ('\n'.join(out), blocks)

def _restore_keep_sections(txt: str, blocks: list[tuple[str, str]]) -> str:
    for placeholder, block in blocks:
        txt = txt.replace(placeholder, block)
    return txt

def scrub_guide_md(md_text: str) -> tuple[str, dict]:
    stats = {'nav_runs': 0, 'run_lines': 0, 'brief_cuts': 0, 'junk_lines': 0, 'bare_urls': 0, 'junk_imgs': 0, 'dropped_sections': 0, 'source_links_kept': 0, 'article_links_unwrapped': 0, 'article_menu_links_dropped': 0, 'content_chrome': 0, 'edit_suffix': 0, 'alt_spam': 0, 'offtopic_sections': []}
    md_text, keep_blocks = _protect_keep_sections(md_text)
    lines = md_text.split('\n')
    out: list[str] = []
    protected = False
    dropped = False
    fence = False
    i = 0
    while i < len(lines):
        ln = lines[i]
        if FENCE_RE.match(ln):
            fence = not fence
            out.append(ln)
            i += 1
            continue
        if fence:
            out.append(ln)
            i += 1
            continue
        if H2_H3_RE.match(ln):
            protected = False
            dropped = False
            if DROP_SECTION_RE.match(ln):
                dropped = True
                stats['dropped_sections'] += 1
                i += 1
                continue
            if _is_bot_challenge_section(ln, lines[i + 1:i + 8]):
                dropped = True
                stats['dropped_sections'] += 1
                i += 1
                continue
            if PROTECT_HEAD_RE.match(ln):
                protected = True
            out.append(ln)
            i += 1
            continue
        if dropped or protected:
            i += 1
            continue
        if TABLE_RE.match(ln):
            j = i
            while j < len(lines) and TABLE_RE.match(lines[j]):
                j += 1
            if _is_navbox_table(lines[i:j]):
                stats['content_chrome'] += j - i
                i = j
                continue
            out.append(ln)
            i += 1
            continue
        if _nav_line(ln):
            j = i
            while j < len(lines) and _nav_line(lines[j]):
                j += 1
            if j - i >= 5:
                stats['nav_runs'] += 1
                stats['run_lines'] += j - i
                i = j
                continue
        if _is_local_img_line(ln):
            out.append(ln)
            i += 1
            continue
        if JUNK_IMG_RE.match(ln):
            stats['junk_imgs'] += 1
            i = _drop_paired_credit(lines, i)
            continue
        if ln.strip().startswith('![') and JUNK_IMG_URL_RE.search(ln):
            stats['junk_imgs'] += 1
            i = _drop_paired_credit(lines, i)
            continue
        if EXEC_RE.match(ln):
            cut = _brief_cut(ln)
            if cut is not None:
                stats['brief_cuts'] += 1
                out.append(ln[:cut].rstrip())
                i += 1
                continue
        s = ln.strip()
        if s and JUNK_LINE_RE.match(s):
            stats['junk_lines'] += 1
            i += 1
            continue
        if s and (NAVBOX_LINE_RE.match(s) or MARKETING_CTA_RE.search(s) or WIKI_FOOTER_RE.search(s)):
            stats['content_chrome'] += 1
            i += 1
            continue
        if re.search('\\w{3,}edit\\b', ln):
            ln = re.sub('(\\w)edit\\b', '\\1', ln)
            stats['edit_suffix'] += 1
        if URL_RE.search(s) and _only_url(s):
            stats['bare_urls'] += 1
            i += 1
            continue
        out.append(ln)
        i += 1
    txt = '\n'.join(out)
    txt = re.sub('(?<!\\!)\\[[^\\]]{300,20000}\\]\\((https?://[^)]+)\\)', lambda m: '' if IMG_HOST_RE.search(m.group(1)) or ASSET_LINK_RE.search(m.group(1)) else m.group(0), txt)
    txt = '\n'.join(out)
    txt = _strip_alt_spam(txt, stats)
    txt = _quarantine_offtopic_sections(txt, stats)
    txt = re.sub('\\n{3,}', '\n\n', txt)
    txt = _strip_article_section_links(txt, stats)
    txt = _restore_keep_sections(txt, keep_blocks)
    stats['source_links_kept'] = len(re.findall('\\[[^\\]]+\\]\\(https?://[^)]+\\)', txt))
    return (txt, stats)
ARTICLE_H3_RE = re.compile('^###\\s+.+\\s[|—–-]\\s*[A-Z][^|—–]{2,40}\\s*$')
ARTICLE_H3_LONG_RE = re.compile('^###\\s+.{50,200}$')

def _is_article_h3(ln: str) -> bool:
    if not ln.startswith('###'):
        return False
    if ARTICLE_H3_RE.match(ln):
        return True
    if ARTICLE_H3_LONG_RE.match(ln):
        t = ln[3:].strip()
        if not re.search('[.!?]\\s*$', t) and (not t.endswith(':')):
            return True
    t = ln[3:].strip()
    if 10 <= len(t) <= 49 and (not re.search('[.!?]\\s*$', t)):
        if re.search('\\b(ETF|ETFs|Bitcoin|BTC|MSTY|NVDY|Yield|Strategy|Schedule|Analysis|Comparison|Dashboard|Charts?|Indicators?|Guide|Data|Price|Yield|Holdings|Performance|Portfolio)\\b', t):
            return True
        if re.match('^(Just a moment|Page Not Found|Attention Required|Access Denied|503|404)\\b', t, re.I):
            return True
    return False
BOT_CHALLENGE_RE = re.compile('^(This website uses a security service|Ray ID:|Performance and Security by Cloudflare|Just a moment|Checking your browser|Please verify you are human|DDoS protection|Enable JavaScript)', re.I)
NAVBOX_LINE_RE = re.compile('^(show\\s+(History|Hacker culture|Conferences|Cybercrime|Hacking tools|Practice sites|Malware|Cybersecurity domains|Groups|Publications|Computer science|Information security)|vte\\b|Authority control databases|Part of a series on|Contents hide|Jump to (content|navigation|search)|Main page$|^Contents$|Categories:)', re.I)
NAVBOX_VOCAB_CELL = re.compile('^(show|vte|hide|contents|edit|talk|view|history|jump to|main page|categories|special pages|printable version|permanent link|page information|cite this page|wikidata item|authority control|software|freeware|operating systems|common features|part of a series|computer hacking|computer security|computer science|information security|process management|interrupts|memory management|file system|device drivers|networking|security|input/output|\\{\\{.*\\}\\}|\\[\\[.*\\]\\]|←|→|‹|›|\\s*)$', re.I)

def _is_navbox_table(block_lines) -> bool:
    rows = 0
    vocab_cells = 0
    total_cells = 0
    for ln in block_lines:
        if not ln.strip().startswith('|'):
            continue
        cells = [c.strip() for c in ln.strip().strip('|').split('|')]
        if all((re.fullmatch(':?-{2,}:?', c) for c in cells)):
            continue
        rows += 1
        for c in cells:
            total_cells += 1
            if NAVBOX_VOCAB_CELL.match(c):
                vocab_cells += 1
    return rows >= 3 and total_cells > 0 and (vocab_cells / total_cells >= 0.7)
NAVBOX_ROW_RE = re.compile('^\\s*\\|(?=\\s*(?:show\\s+\\w|vte\\b|Hide\\b|Contents\\b|edit\\b|talk\\b|view\\b|history\\b|Jump to|Main page|Categories\\b|Authority control|Special pages|Printable version|Permanent link|Page information|Cite this page|Wikidata item|\\[edit\\]))', re.I)
NAVBOX_VOCAB = re.compile('^(show|vte|hide|contents|edit|talk|view|history|jump to|main page|categories|special pages|printable version|permanent link|page information|cite this page|wikidata item|authority control|software|freeware|operating systems|common features|part of a series|computer hacking|computer security|computer science|information security|process management|interrupts|memory management|file system|device drivers|networking|security|input/output|\\{\\{.*\\}\\}|\\[\\[.*\\]\\]|←|→|‹|›)$', re.I)
MARKETING_CTA_RE = re.compile("(Get the (guide|report)|Read the (report|guide|article)|Subscribe\\b|newsletter|Watch the (webinar|latest|podcast)|Listen to|Explore (IBM|Fortinet|our|Cisco).{0,40}(solutions|services|security)|Request a (quote|demo)|Free demo|Take the next step|Learn fast from expert|Join security leaders|All fields required|Your subscription will be delivered|unsubscribe link|cookie preferences|Accept All|More options|SCHOOL NAME.*PROGRAM|MORE INFO|Southern New Hampshire|UC Berkeley School of Information|AD FEATURED|SPONSORED|Sponsored Ad|ONLINE PROGRAMS|ONLINE BACHELOR|ONLINE MASTER|ONLINE PHD|BOOTCAMPS|CERTIFICATIONS\\b.*AZURE|RESOURCE CENTER|INDUSTRIES$|PODCAST|WEBINAR|On-demand webinars|Editors$|Staff (Editor|Writer)|Written by|Last updated:|Would your team catch|Join (security leaders|thousands)|CommunityShare knowledge|DeveloperAccess digital|DocumentationUnderstand|ImplementationDrive|TrainingDevelop|Technology Lifecycle|First name|Last name|Business email|We appreciate your feedback|SUBMIT$|Terms & Conditions|Your Privacy Choices|Holy See|Sint Maarten|I consent to receive|PRODUCTS\\s+MSSP|PARTNERS\\s+TRUST|REQUEST A QUOTE|CONNECT WITH US|Of Interest|Explore .* (solutions|services)|Discover (IBM|Fortinet)|Read the latest|Footnotes$|GFG App on (Play|App) Store|App on (Play|App) Store|Corporate & Communications Address|Registered Address|Trending Technologies|POTD |DSA |GATE |accessibility_testing_methods|major_cyber_attacks|AD FEATURED CYBERSECURITY|ONLINE PROGRAMS Master|Why readers trust|500,000\\+ annual visitors|750\\+ cybersecurity degree|80\\+ expert contributors|50\\+ free career|^Podcast |^PODCAST|Written by Steven Bowcut|With over 30 years of experience|This guide is intended to provide an introduction|Beginning with a few of the relevant terms|The challenge of securing personal information|Motivated by politics, social activism, or greed, threat actors|This evolving threat landscape has also fueled growth|But a more pertinent question|Services$|Watch the latest|Security Intelligence \\| \\d+|Learn more about (cyber|phishing|ethical)|About cookies on this site|Our websites require some cookies|Explore every facet|The 2026 Guide to Cybersecurity|Cybersecurity guide Cybersecurity in the era|Editors$|Staff Editor$|Staff Writer$|Senior AI Advocate|Matthew Kosinski|Bryan Clark|Mark Scapicchio|Alexandra Jonker|Gregg Lindemulder|Explore tutorials|Expand your skills|IAM explainer|What is identity and access management|Cost of a Data Brereach|Cost of a Data Breach Report 2026|KuppingerCole report|TEI report|Gartner Market Guide|On-demand webinars|Security tutorials|Cybersecurity guide|Take the next step|Discover IBM|Explore IBM|CommunityShare|DeveloperAccess|DocumentationUnderstand|ImplementationDrive|TrainingDevelop|Technology Lifecycle|IBM Cloud platform|Access subject matter experts|IBM Guardium|Protect your most critical data|Transform your security|Transform your business|A light bulb with an explosion|IBM-Guardium-Data-Protection-Social-Asset|Can you trust your recovery strategy|Smarter AI governance|governance and security into drivers|See why KuppingerCole ranks|The total economic impact|Discover the benefits and ROI|Access this Gartner|AI TRiSM|trust for all AI use cases|Follow clear steps|complete tasks and learn how|Explained: How It Works|identity and access management \\(IAM\\)|Cybersecurity statistics|Cybersecurity Mesh|Cyber Insurance|What is a Cyber|What is Cyber Safety|What is Cyber Attack|IT vs OT|AI Cybersecurity|Privacy Policy$|cookie preferences|Back to top|Can't find what you're looking for|Useful links|GCHQ MI5|Was this article helpful|Yes$|No$|Home X LinkedIn|Instagram Threads RSS|CyberGlossary|Multi-Layered Defense|2026 THREAT LANDSCAPE|2026 Global Threat Landscape|Key Takeaways|Download Now|Click to See Larger|A rising challenge|Build core skills|With IBM SkillsBuild|The different types of cybersecurity|types of cyberattacks|most common types of cyberattacks|Common cybersecurity myths|Myth #|myths persist|cybersecurity best practices|Data security tools$|Identity and access management$|Attack surface management$|Threat detection and response$|Disaster recovery$|Managed security$|10 cybersecurity best practices|How to choose the right cybersecurity|Converge key networking|single source of threat intelligence|single-pane-of-glass|Hybrid Mesh Firewall|Fortinet's cybersecurity platform|Fortinet Security Fabric|Secure Networking:|Security Operations:|FortiSASE|Rising cyber threats put your cloud|Cybersecurity FAQs|How can businesses ensure|How often should an organization|What cybersecurity regulations|Cybersecurity Resources|Cyber Threat Intelligence|What is Cyber Safety|IT vs OT Cybersecurity|Please fill out the form|knowledgeable representative|A complex networking and application infrastructure|Understanding the criteria for a cyber threat|Six cyber threats|Essential cybersecurity components|Key cybersecurity technologies|Cybersecurity infographic|Cyber resilience lifecycle|What is Cybersecurity\\?$|fortinet security fabric pillar|Click to See Larger Image|Diagram showing the six core domains|How training and managed services|FortiAI applies|Automated threat detection:|Autonomous incident response:|Behavioral analytics:|AI-powered threat intelligence:|Agentic AI and autonomous|Post-quantum cryptography|Regulatory acceleration|Platform convergence|Cybersecurity workforce gap|How AI is transforming|Strategic cybersecurity tools|Advanced cybersecurity solutions|Data loss prevention \\(DLP\\)|Endpoint detection and response \\(EDR\\)|Intrusion prevention systems \\(IPS\\)|Next-generation firewalls|Secure access service edge|SASE combines|Security information and event management|Security orchestration, automation|SOAR platforms|Emerging trends driving cybersecurity|Key cybersecurity trends shaping|Fortinet's analysis of AI|skills-based hiring|Cybersecurity certification programs|Cybersecurity awareness|Managed cybersecurity services|hybrid of both|MDR, or managed detection|XDR, or extended detection|MSSPs give organizations|hybrid environments, including|Use frequent, periodic data backups|Implement multi-factor|Provide ongoing cybersecurity training|Use proper password hygiene|Leverage encryption software|Regularly update software|Limit user privileges|Develop an incident response plan|Segment the network|Conduct regular security audits|Also read through this elaborate checklist|Spotting and preventing cyberthreats|harden U.S. government|Cybersecurity isn't a singular solution|Network security safeguards communication|Information security, or InfoSec|Cloud security refers|Endpoint security focuses|Application security refers|Zero trust security is|Zero trust is a modern|Operational technology \\(OT\\)|IoT security also focuses|Identity security and access management|AI security is an emerging|AI governance is becoming|In this context, AI security refers|Critical infrastructure security protects|Network security focuses on preventing|Application security \\(AppSec\\)|Modern application development|Cloud security secures an organization|Information security \\(InfoSec\\) protects|Identity security focuses on protecting|discover, analyze, remediate and monitor|continuous discovery, analysis, remediation|Security information and event management \\(SIEM\\)|managed detection and response combines|extended detection and response takes|firewall management to more advanced|consistent coverage and faster response|threat intelligence, security tooling|threat actors online$.Financial Times|National Cyber Force|National Cyber Strategy of the United|University Libraries UNT|white house$|US gov\\.|Executive Order on Improving|full text\\) White|National security strategy.*PDF|Biden Adviser On Cyber Threats|NPR\\. Executive Order|NPR\\.|Kelly, Mary Louise|Sanger, David \\(5 June|Barrett, Devlin|Zengerle, Patricia|Risen, Tom|Liptak, Kevin|Gallagher, Sean|Davis, Michelle|Perlroth, Nicole|Newman, Lily|Seipel, Hubert|Riley, Michael|Elgin, Ben|Matlack, Carol|Rosenblatt, Seth|Cowley, Stacy|Sanger, David E|Neumann, P. G|Dillingham, Gerald|Kang, Cecilia|Checkoway, Stephen|Greenberg, Andy|Kirk, Jeremy|Kaiser Health News|The Daily Beast|Backman, Melvin|Palilery, Jose|Pagliery, Jose|Turton, W\\.|Finkle, Jim|Cesar, Alan|Kuchler, Hannah|Kruse, CB|Singh, Jatinder|Krishnan, Anant|Schectman, Joel|Bing, Christopher|Branch, Jordan|Costigan, Sean|Hennessy, Michael|Chwan-Hwa|Fuller, Christopher|Bob, Yonah|Lee, Newton|Lin, Tom C\\.|Cole, Jeffrey|Schariati, Marzieh|Montagnani, Maria|Calder, Alan|Johnson, A\\.|Foreman, Park|Oppliger, Rolf|Woodie, Alex|Walkowski, Debbie|Jannsen, Cory|Irwin, Luke|Souppaya, Murugiah|Scarfone, Karen|Stoneburner, G|Ferraiolo, D\\.F|Sandhu, R;|Abreu, Vilmar|Harrison, J\\.|Hassija, Vikas|Tomlinson, Ray|Neumann, A\\. J|Yost, Jeffrey|Misa, Thomas|Greene, James|Cook, James|Anderson, Nate|Bright, Peter|Scannell, Kara|Lazar, Ari|York, Dan|Butterfield, Andrew|Marcel, Sébastien|Gallagher, Sean|Lim, Joo S|Arcos Sergio|Millman, Renee|Treglia, J|Delia, M|Reimers, Karl|Andersson, David|Schlienger, Thomas|Teufel, Stephanie|Walker, John|Caldwell, Tracey|Kaljulaid, Kersti|Kuchler, Hannah|Clearfield, Chris|Vermesan, Ovidiu|Friess, Peter|Sztyber-Betley|Sanghavi, Alok|Bullard, Brittany|Oltsik, Jon|Robinson, Terry|de Silva, Richard|Verton, Dan|Largent, Jonathan|Leswing, April|Thompson, Zan)|Pauli, Darren|Cook, James|Lee, Timothy|Zetter, Kim|Reals, Tucker|Nakashima, Ellen|Overland, Indra|Maness, Ryan|Valeriano, Brandon|Bullard, Brittany|Clayton, Mark|Bumgarner, John|Shachtman, Noah|Lynn, William|Warrell, Helen|Sengupta, Kim|Targett, Edward|Jun, Kwanwoo|Sternstein, Aliya|Elias, Bart|Cesar, Alan|Cashell, B|Gordon, Lawrence|Loeb, Martin|Sanger, David E|Barrett, Devlin|Risen, Tom|Zengerle, Patricia|Davis, Michelle|Perlroth, Nicole|Treglia, J|ROhM|Crime$|Computer Crime|HBGary|Anonymous hack|LulzSec|Antisec|WikiLeaks|Guccifer|DCLeaks|Fancy Bear|Cozy Bear|Energetic Bear|Sandworm|Turla|APT28|APT29|Equation Group|Carbanak|FIN7|FIN8|TA505|Wizard Spider|Conti |Ryuk |REvil |Sodinokibi|DarkSide|BlackMatter|LockBit|ALPHV|BlackCat|Clop|Cl0p|Play ransomware|Royal ransomware|Akira |Qilin |RansomHub|Medusa |Hunters International|DragonForce|Gentlemen|Palo Alto|Unit 42|Mandiant|Google Threat|Recorded Future|CrowdStrike |SentinelOne|Microsoft Threat|Volexity|ESET |Bitdefender|Kaspersky|Symantec|McAfee|Trellix|Palo Alto Networks|Check Point|Fortinet|Zscaler|SentinelOne|Carbon Black|Vectra AI|Darktrace|ExtraHop|Nozomi Networks|Claroty|Dragos|Tenable|Qualys|Rapid7|Cisco Talos|IBM X-Force|Google Cloud|Unit 42 Cloud|Threat Intelligence Index|Cost of a Data Breach Report|X-Force Threat Intelligence Index|Threat Intelligence Index 2026|Cost of a Data Breach 2026|IBM X-Force®|Guardium®|FortiAI|FortiSASE|FortiEDR|FortiXDR|Security Fabric|Hybrid Mesh Firewall|Gartner Magic Quadrant|Gartner Peer Insights|Forrester Wave|KuppingerCole Leadership|IDC MarketScape|Omdia|451 Research|Forrester TEI|total economic impact|Return on Investment|ROI of|benchmark against|compared to industry|best-in-class|leading provider|market leader|leader in the|recognized as a leader|positioned as a leader|named a leader|leader for the|customers worldwide|enterprises globally|trusted by millions|used by millions|over \\d+ (million|billion) customers|more than \\d+ (million|billion)|industry-leading|award-winning|cutting-edge|state-of-the-art|robust|comprehensive|end-to-end|scalable|flexible|powerful solution|seamless integration|plug-and-play|transform your|revolutionize your|unlock the power|leverage the power|take your security to the next level|stay ahead of threats|stay one step ahead|peace of mind|sleep soundly|protect what matters most|your trusted partner|partner with us|get started today|start your free trial|sign up now|contact us today|request a demo|schedule a call|speak with an expert|talk to sales|pricing starts at|plans start at|per month\\)|per year\\)|per user|billed annually|billed monthly|no credit card required|14-day free trial|30-day free trial|cancel anytime|money-back guarantee|terms and conditions apply|all rights reserved|© 20\\d\\d|©\\d{4}|&copy;", re.I)
WIKI_EDIT_SUFFIX_RE = re.compile('\\bedit\\b(?=\\s|$)', re.I)
WIKI_FOOTER_RE = re.compile('This page was (last edited|last modified) on|Page was rendered with Parsoid|Text is available under the Creative Commons|additional terms may apply|Wikipedia® is a registered trademark|By using this site, you agree to the Terms of Use', re.I)

def _is_bot_challenge_section(heading: str, next_lines: list[str]) -> bool:
    if re.match('^##+\\s*(Just a moment|Page Not Found|Attention Required|Access Denied|404|503)\\b', heading, re.I):
        return True
    for ln in next_lines[:6]:
        s = ln.strip()
        if s and BOT_CHALLENGE_RE.match(s):
            return True
    return False
MENU_LINK_RE = re.compile('^\\s*[-*]?\\s*(?<!\\!)\\[[^\\]]{1,60}\\]\\(https?://[^)]+\\)\\s*$')
MULTILINE_MENU_LINK_RE = re.compile('\\[([^\\]]{1,40}?)\\s*\\n\\s*[^\\]]{0,200}\\]\\(https?://[^)]+\\)')
NAV_LIST_LINK_RE = re.compile('^\\s*[-*]\\s*(?<!\\!)\\[(?:https?://[^\\]|]{5,80}|[A-Z][A-Za-z &/]{2,30})\\]\\((https?://[^)]+)\\)\\s*$')
MD_LINK_RE = re.compile('(?<!\\!)\\[([^\\]]+)\\]\\(https?://[^)]+\\)')
ASSET_LINK_RE = re.compile('https?://[^)]*(?:wp-admin|wp-content|wp-includes|favicon\\.ico|/assets?/|/static/|/img/|/images/|/icons?/|/logos?/|/thumbs?/|cloudflare\\.com/\\?utm|\\.svg\\b|\\.ico\\b|google-analytics|googletagmanager|doubleclick|/cdn-cgi/|admin-ajax)', re.I)
MARKETING_HOST_RE = re.compile('https?://(?:www\\.)?(?:binance\\.com|coinbase\\.com|coingecko\\.com|coindesk\\.com|investopedia\\.com|tradingview\\.com|bitbo\\.io|charts\\.bitbo\\.io|lookintobitcoin\\.com|myplaniq\\.com|portfolioslab\\.com|dividend\\.com|etfdb\\.com|stockanalysis\\.com|finance\\.yahoo\\.com|nasdaq\\.com|seekingalpha\\.com|graniteshares\\.com|yieldmaxetfs\\.com|bebooja\\.com|weeklyyield\\.com|wisesheets\\.io|fintel\\.io|marketbeat\\.com|simplywall\\.st|zacks\\.com|fool\\.com|thestreet\\.com|benzinga\\.com|morningstar\\.com|dividenddata\\.com|defenseworld\\.net|yieldmaxcalc\\.com|stockhouse\\.com|etftrends\\.com|etfdb\\.com|dividend\\.com|nasdaq\\.com)\\b', re.I)
NEWSWIRE_HOST_RE = re.compile('https?://(?:www\\.)?(?:globenewswire\\.com|businesswire\\.com|prnewswire\\.com|accesswire\\.com|newswire\\.ca|marketwatch\\.com|seekingalpha\\.com|benzinga\\.com|thestreet\\.com|fool\\.com|zacks\\.com|streetinsider\\.com|investing\\.com)\\b', re.I)
CF_PRIVACY_RE = re.compile('https?://(?:www\\.)?cloudflare\\.com/(?:privacypolicy|privacy-policy|legal)', re.I)
AUTHORITY_HOST_RE = re.compile('https?://(?:www\\.)?(?:(?:[a-z]+\\.)?gov(?:/[a-z]{2})?\\b|(?:[a-z]+\\.)?mil\\b|nist\\.gov|nist\\.org|iso\\.org|ietf\\.org|w3\\.org|en\\.wikipedia\\.org|wikipedia\\.org|arxiv\\.org|acm\\.org|ieee\\.org|doi\\.org|mitre\\.org|attack\\.mitre\\.org|cisa\\.gov|sec\\.gov|ftc\\.gov|fcc\\.gov|justice\\.gov|europol\\.europa\\.eu|interpol\\.int|who\\.int|irs\\.gov|ssa\\.gov|consumerfinance\\.gov|ec\\.europa\\.eu|europa\\.eu|us-cert\\.circl\\.lu|icann\\.org|azleg\\.gov|azcourts\\.gov|azsos\\.gov|azdhs\\.gov|courts\\.state\\.[a-z]+\\.us|ca\\.courts\\.ca\\.gov|law\\.cornell\\.edu|casetext\\.com|justia\\.com|law\\.justia\\.com|congress\\.gov|govinfo\\.gov|uscode\\.house\\.gov|azleg\\.gov|legis\\.laws\\.com|statelaws\\.findlaw\\.com)', re.I)
IMG_HOST_RE = re.compile('https?://(?:storage\\.googleapis\\.com|static\\.|assets\\.|dynamic-assets\\.|asset-metadata-service|images\\.|thumb\\.|cdn\\.|media\\.)|s3\\.amazonaws\\.com|\\.png\\b|\\.jpg\\b|\\.jpeg\\b|\\.webp\\b|\\.gif\\b', re.I)

def _strip_article_section_links(txt: str, stats: dict) -> str:
    txt = re.sub('\\[(?:GraniteShares|YieldMax|Leverage Shares|Roundhill|Defiance|ProShares)[^\\]]{0,80}\\n\\s*[^\\]]{10,200}\\]\\(https?://[^)]+\\)', '', txt)

    def _junk_anchor(m):
        anchor, url = (m.group(1), m.group(2))
        if IMG_HOST_RE.search(url) or ASSET_LINK_RE.search(url):
            return ''
        first_line = anchor.split('\n')[0].strip()
        return first_line
    txt = re.sub('(?<!\\!)\\[([^\\]]{0,200})(?:\\n- \\[|\\n\\d+\\.|\\n#|\\|)[^\\]]{0,600}\\]\\((https?://[^)]+)\\)', _junk_anchor, txt)
    txt = MULTILINE_MENU_LINK_RE.sub(lambda m: m.group(1).strip(), txt)
    txt = MD_LINK_RE.sub(lambda m: m.group(1) if PROSE_UNWRAP_HOST_RE.search(m.group(0)) else m.group(0), txt)
    lines = txt.split('\n')
    out = []
    in_article = False
    unwrapped = 0
    dropped = 0
    for ln in lines:
        if re.match('^##+ ', ln):
            in_article = _is_article_h3(ln)
            out.append(ln)
            continue

        def _drop_chrome(m):
            url = m.group(0)
            if ASSET_LINK_RE.search(url) or MARKETING_HOST_RE.search(url):
                return ''
            if NEWSWIRE_HOST_RE.search(url) or CF_PRIVACY_RE.search(url):
                return m.group(1)
            if IMG_HOST_RE.search(url):
                return m.group(1) if m.group(1).strip() else ''
            return url
        ln = MD_LINK_RE.sub(_drop_chrome, ln)
        if not in_article:
            out.append(ln)
            continue
        if MENU_LINK_RE.match(ln) or NAV_LIST_LINK_RE.match(ln):
            dropped += 1
            continue

        def _unwrap(m):
            if AUTHORITY_HOST_RE.search(m.group(0)):
                return m.group(0)
            nonlocal unwrapped
            unwrapped += 1
            return m.group(1)
        out.append(MD_LINK_RE.sub(_unwrap, ln))
    stats['article_links_unwrapped'] = unwrapped
    stats['article_menu_links_dropped'] = dropped
    return '\n'.join(out)

def _strip_alt_spam(txt: str, stats: dict) -> str:
    lines = txt.split('\n')
    out = []
    seen_recent: dict[str, int] = {}
    dropped = 0
    for ln in lines:
        s = ln.strip()
        if s and (not s.startswith(('#', '|', '>', '!', '-', '*', '`'))) and ('](http' not in s) and (10 <= len(s) <= 90):
            key = s.lower()
            if seen_recent.get(key, 0) >= 1 and len(out) > 3:
                dropped += 1
                continue
            seen_recent[key] = seen_recent.get(key, 0) + 1
        else:
            seen_recent.clear()
        out.append(ln)
    stats['alt_spam'] = dropped
    return '\n'.join(out)

def _flag_offtopic_sections(txt: str, stats: dict, title: str='') -> None:
    before = len(stats.get('offtopic_sections') or [])
    kept = {'offtopic_sections': []}
    _quarantine_offtopic_sections(txt, kept, enforce=False)
    stats.setdefault('offtopic_sections', []).extend(kept['offtopic_sections'])

def _quarantine_offtopic_sections(txt: str, stats: dict, title: str='', enforce: bool=True) -> str:
    stats.setdefault('quarantined_sections', [])
    if not title:
        pass
    m = re.search('^#\\s+(.*)$', txt, re.M)
    if not m:
        return txt
    title_tokens = set(re.findall('[a-z]{4,}', m.group(1).lower()))
    if not title_tokens:
        return txt
    stop = {'guide', 'master', 'research', 'everything', 'complete', 'ultimate', 'introduction', 'overview', 'what', 'your', 'with', 'from', 'into'}
    title_tokens -= stop
    if not title_tokens:
        return txt
    lines = txt.split('\n')
    blocks: list = []
    cur_head, cur = (None, [])
    for ln in lines:
        if re.match('^## ', ln):
            if cur_head is not None or cur:
                blocks.append((cur_head, cur))
            cur_head, cur = (ln, [])
        else:
            cur.append(ln)
    if cur_head is not None or cur:
        blocks.append((cur_head, cur))
    out_lines: list = []
    for head, body in blocks:
        if head is None:
            out_lines.extend(body)
            continue
        words = []
        for ln in body:
            words += re.findall('[a-z]{4,}', ln.lower())
        section_stat = {'section': head.lstrip('#').strip()[:80]}
        if DROP_SECTION_RE.match(head) or PROTECT_HEAD_RE.match(head):
            out_lines.append(head)
            out_lines.extend(body)
            continue
        if len(words) < 80:
            out_lines.append(head)
            out_lines.extend(body)
            continue
        toks = set(words)
        overlap = len(toks & title_tokens) / max(len(title_tokens), 1)
        htoks = set(re.findall('[a-z]{4,}', head.lower())) - stop
        hover = len(htoks & title_tokens) / max(len(htoks), 1) if htoks else 0
        section_stat['overlap'] = round(overlap, 3)
        if overlap < 0.02 and hover < 0.15:
            stats['offtopic_sections'].append(section_stat)
            if enforce:
                stats['quarantined_sections'].append(section_stat)
                continue
        out_lines.append(head)
        out_lines.extend(body)
    return '\n'.join(out_lines)

def _brief_cut(line: str):
    for a in BRIEF_CUT_ANCHORS:
        k = line.find(a)
        if k != -1:
            if k >= 40:
                return k
    return None

def _cli(argv: list[str]) -> int:
    ap = __import__('argparse').ArgumentParser(description='Scrub nav chrome from Master Guides (--write to save; creates <file>.orig backups)')
    ap.add_argument('files', nargs='+')
    ap.add_argument('--write', action='store_true')
    args = ap.parse_args(argv)
    for f in argv and args.files:
        p = Path(f)
        if not p.exists():
            print(f'  ! missing: {p}')
            continue
        md = p.read_text(errors='replace')
        new, stats = scrub_guide_md(md)
        if args.write:
            orig = p.with_suffix(p.suffix + '.orig')
            if not orig.exists():
                orig.write_text(md)
            p.write_text(new)
        print(f"  {p.name}: runs={stats['nav_runs']}({stats['run_lines']}L) briefcuts={stats['brief_cuts']} junk={stats['junk_lines']} urls={stats['bare_urls']} imgs={stats['junk_imgs']} dropped={stats['dropped_sections']}s unwrapped={stats['article_links_unwrapped']} menu_dropped={stats['article_menu_links_dropped']} links_left={stats['source_links_kept']}")
    return 0
if __name__ == '__main__':
    sys.exit(_cli(sys.argv[1:]))