"""Add Morph transitions and staged entrance animations to the pptxgenjs deck.

Every slide gets a Morph transition (fade fallback for viewers without Morph); the shared
"!!drop" circle glides between slides. Shapes whose name starts with "anim-" float in after the
slide opens, grouped by their name stem ("anim-e0", "anim-e0-h", "anim-e0-n" enter together),
in document order, without clicks. Usage: python3 animate_deck.py in.pptx out.pptx
"""

from __future__ import annotations

import re
import sys
import zipfile

TRANSITION = (
    '<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
    '<mc:Choice xmlns:p159="http://schemas.microsoft.com/office/powerpoint/2015/09/main" Requires="p159">'
    '<p:transition xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main" spd="slow" p14:dur="1400">'
    '<p159:morph option="byObject"/></p:transition></mc:Choice>'
    '<mc:Fallback><p:transition spd="slow"><p:fade/></p:transition></mc:Fallback>'
    "</mc:AlternateContent>"
)

SHAPE = re.compile(r'<p:cNvPr id="(\d+)" name="([^"]*)"')


def stem(name: str) -> str:
    # anim-e0-h -> anim-e0 ; anim-shot-frame -> anim-shot ; anim-k0s-n -> anim-k0s
    parts = name.split("-")
    return "-".join(parts[:2])


def effect(ids: list[int], spid: str, delay: int, dur: int = 700) -> str:
    def nid() -> int:
        ids[0] += 1
        return ids[0]

    tgt = f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>'
    pos = lambda attr, frm: (
        f'<p:anim calcmode="lin" valueType="num"><p:cBhvr additive="base"><p:cTn id="{nid()}" dur="{dur}" fill="hold"/>'
        f"{tgt}<p:attrNameLst><p:attrName>{attr}</p:attrName></p:attrNameLst></p:cBhvr>"
        f'<p:tavLst><p:tav tm="0"><p:val><p:strVal val="{frm}"/></p:val></p:tav>'
        f'<p:tav tm="100000"><p:val><p:strVal val="#{attr}"/></p:val></p:tav></p:tavLst></p:anim>'
    )
    outer = nid()
    inner = nid()
    return (
        f'<p:par><p:cTn id="{outer}" fill="hold"><p:stCondLst><p:cond delay="{delay}"/></p:stCondLst><p:childTnLst>'
        f'<p:par><p:cTn id="{inner}" presetID="42" presetClass="entr" presetSubtype="0" fill="hold" nodeType="afterEffect">'
        f'<p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
        f'<p:set><p:cBhvr><p:cTn id="{nid()}" dur="1" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>'
        f"{tgt}<p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>"
        f'<p:to><p:strVal val="visible"/></p:to></p:set>'
        f'<p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn id="{nid()}" dur="{dur}"/>{tgt}</p:cBhvr></p:animEffect>'
        + pos("ppt_x", "#ppt_x")
        + pos("ppt_y", "#ppt_y+.06")
        + "</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>"
    )


def timing(groups: list[list[str]]) -> str:
    ids = [3]
    pars = []
    for i, spids in enumerate(groups):
        delay = 350 + i * 320
        for sp in spids:
            pars.append(effect(ids, sp, delay))
    return (
        '<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
        '<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
        '<p:par><p:cTn id="3" fill="hold"><p:stCondLst><p:cond delay="indefinite"/>'
        '<p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond></p:stCondLst><p:childTnLst>'
        + "".join(pars)
        + "</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn>"
        '<p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
        '<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst>'
        "</p:seq></p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>"
    )


def animate(xml: str) -> str:
    order: list[str] = []
    by: dict[str, list[str]] = {}
    for sid, name in SHAPE.findall(xml):
        if not name.startswith("anim-"):
            continue
        k = stem(name)
        if k not in by:
            by[k] = []
            order.append(k)
        by[k].append(sid)
    extra = TRANSITION + (timing([by[k] for k in order]) if order else "")
    xml = re.sub(r"<p:transition\b.*?</p:transition>|<p:timing>.*?</p:timing>", "", xml, flags=re.DOTALL)
    return xml.replace("</p:clrMapOvr>", "</p:clrMapOvr>" + extra, 1)


def main(src: str, dst: str) -> None:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", item.filename):
                text = data.decode("utf-8")
                if "</p:clrMapOvr>" not in text:
                    raise SystemExit(f"{item.filename}: no clrMapOvr to anchor the transition")
                data = animate(text).encode("utf-8")
            zout.writestr(item, data)
    print(f"animated {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
