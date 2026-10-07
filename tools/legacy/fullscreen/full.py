import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from PIL import Image, ImageChops
import fx as FXMOD
ROOT=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
W,H=1920,1080
art=FXMOD.FullscreenArt(W,H)
spr=Image.open(os.path.join(ROOT,"assets","main.png")).convert("RGBA")
spr=spr.resize((int(spr.width*525/spr.height),525), Image.LANCZOS)
cx,cy=1300,760                      # 她大致站的位置

def frame(p, wall):
    bg=wall.copy()
    lay=Image.new("RGBA",(W,H),(0,0,0,0))
    art.draw(lay,cx,cy-180,p)
    bg.alpha_composite(lay)
    bg.paste(spr,(int(cx-spr.width/2),int(cy-spr.height)),spr)
    return bg

for name,col in (("dark",(26,22,44,255)),("light",(232,233,238,255))):
    wall=Image.new("RGBA",(W,H),col)
    ps=[0.10,0.18,0.28,0.42,0.60,0.80]
    sheet=Image.new("RGB",(W//2*3, H//2*2),(0,0,0))
    for i,p in enumerate(ps):
        f=frame(p,wall).resize((W//2,H//2),Image.LANCZOS).convert("RGB")
        sheet.paste(f,((i%3)*(W//2),(i//3)*(H//2)))
    sheet.save(os.path.join(ROOT,"_fxdev2",f"full_{name}.png"))

# 性能
lay=Image.new("RGBA",(W,H),(0,0,0,0))
def premul(img):
    a=img.getchannel("A")
    return Image.merge("RGBA",(ImageChops.multiply(img.getchannel("R"),a),
                               ImageChops.multiply(img.getchannel("G"),a),
                               ImageChops.multiply(img.getchannel("B"),a),a))
t=time.perf_counter()
N=20
for i in range(N):
    lay.paste((0,0,0,0),(0,0,W,H))
    art.draw(lay,cx,cy-180,0.05+0.9*(i/N))
draw_ms=(time.perf_counter()-t)/N*1000
t=time.perf_counter()
for _ in range(10): premul(lay).tobytes()
push_ms=(time.perf_counter()-t)/10*1000
print(f"全屏 {W}x{H}:  绘制 {draw_ms:.1f} ms/帧   预乘+取字节 {push_ms:.1f} ms/帧   合计 {draw_ms+push_ms:.1f} ms")
