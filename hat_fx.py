"""I-29: baked hat dust and thinking wisps, with fixed storage and no runtime filters.

Coordinates and velocities are pixels in FX's supersampled frame. The fixed
orbit track is geometry, not a particle field. Moving hat bodies (3), trail
samples (30) and smoke slots (12) together stay below the 48-particle limit.
"""
import math
from pathlib import Path

from PIL import Image

MAX_PARTICLES = 48
TRAIL_SAMPLES = 10
SMOKE_SLOTS = 12
ALPHAS = (0, .12, .22, .34, .48, .62, .78, .95)
ASSETS = ('dust-gold', 'dust-lilac', 'dust-blue', 'dust-mote',
          'smoke-lilac', 'smoke-blue')
HEADROOM = 20  # transparent viewport only; panel geometry and font size stay fixed


def bake(assets_dir, pixel_scale):
    """Called only by FX.build. Generated halo and vapor are kept in the sprites."""
    if assets_dir is None:
        return None
    root = Path(assets_dir) / 'hat_fx_v1'
    table = []
    for name, extent in zip(ASSETS, (12, 12, 12, 9, 36, 36)):
        try:
            with Image.open(root / (name + '.png')) as source:
                source = source.convert('RGBA')
                box = source.getchannel('A').point(lambda a: 255 if a > 4 else 0).getbbox()
                if not box:
                    return None
                # Aspect-preserving, premultiplied resize; no runtime blur/resize.
                source = source.crop(box)
                factor = max(2, extent * pixel_scale) / max(source.size)
                size = tuple(max(1, round(v * factor)) for v in source.size)
                sprite = source.convert('RGBa').resize(size, Image.Resampling.LANCZOS).convert('RGBA')
                steps = [None]
                for alpha in ALPHAS[1:]:
                    faded = sprite.copy()
                    faded.putalpha(sprite.getchannel('A').point(lambda v, a=alpha: round(v*a)))
                    steps.append(faded)
                table.append(steps)
        except (OSError, ValueError):
            return None
    return HatFX(table, pixel_scale)


def tip_anchor(image):
    """Find the hat apex in its known upper-right region once, at scale rebuild."""
    w,h=image.size;left,right=round(w*.55),round(w*.75)
    alpha=image.getchannel('A').crop((left,0,right,max(1,round(h*.12))))
    box=alpha.point(lambda v:255 if v>=96 else 0).getbbox()
    if not box:
        return .64,.003
    y=box[1];xs=[x for x in range(alpha.width) if alpha.getpixel((x,y))>=96]
    return (left+sum(xs)/len(xs))/w,y/h


class HatFX:
    def __init__(self, sprites, pixel_scale):
        self.sprites = sprites
        self.scale = pixel_scale
        # Allocate each slot once. Updating a slot changes only numeric fields.
        self.trails = [[[0.,0.,0.,-1e9] for _ in range(TRAIL_SAMPLES)] for _ in range(3)]
        self.heads = [0,0,0]
        self.sampled = [-1e9]*3
        self.last_xy = [[0.,0.] for _ in range(3)]
        self.smoke = [[-1e9,0.,0.,0.,0.] for _ in range(SMOKE_SLOTS)]
        self.next_smoke = 0.
        self.smoke_head = 0
        self.now = 0.
        self.fast = True
        self.thinking = False
        self.last_update = None

    def clear(self):
        for track in self.trails:
            for slot in track:
                slot[3] = -1e9
        for slot in self.smoke:
            slot[0] = -1e9
        self.sampled[:] = [-1e9]*3
        self.next_smoke = 0.
        self.thinking = False

    def update(self, now, items, tip_x, tip_y, fast=True, moving=True):
        if self.last_update is not None and (now < self.last_update or now-self.last_update > 2):
            self.clear()  # suspend/resume does not backfill a cloud
        self.last_update = self.now = now
        self.fast = bool(fast)
        interval = .075 if self.fast else .125
        if moving:
            cx=cy=0.;count=0
            for name,x,y,depth,near,level in items:
                if name=='path':
                    cx+=x;cy+=y;count+=1
            if not count:
                for name,x,y,depth,near,level in items:
                    if name in ('moon','crystal','planet'):
                        cx+=x;cy+=y;count+=1
            center_x=cx/max(1,count);center_y=cy/max(1,count)
            for name,x,y,depth,near,level in items:
                index = 0 if name=='moon' else 1 if name=='crystal' else 2 if name=='planet' else -1
                if index<0 or now-self.sampled[index]<interval:
                    continue
                last=self.last_xy[index]
                if self.sampled[index]>0 and math.hypot(x-last[0],y-last[1])>28*self.scale:
                    for slot in self.trails[index]:slot[3]=-1e9
                self.last_xy[index][0]=x;self.last_xy[index][1]=y
                slot=self.trails[index][self.heads[index]]
                # A tiny offset to the exterior of the old orbit, never towards the face.
                dx,dy=x-center_x,y-center_y;length=max(1.,math.hypot(dx,dy))
                slot[0]=x+dx/length*12*self.scale;slot[1]=y+dy/length*12*self.scale
                slot[2]=depth;slot[3]=now
                self.heads[index]=(self.heads[index]+1)%TRAIL_SAMPLES
                self.sampled[index]=now

    def set_thinking(self, now, active, tip_x, tip_y):
        active=bool(active)
        if not active:
            self.thinking=False;self.next_smoke=now
            return
        if not self.thinking:
            self.next_smoke=now
        self.thinking=True
        if now<self.next_smoke:
            return
        slot=self.smoke[self.smoke_head]
        ordinal=self.smoke_head
        slot[0]=now;slot[1]=tip_x;slot[2]=tip_y
        slot[3]=math.sin(ordinal*2.4)*1.5*self.scale
        slot[4]=4+(ordinal%2) if ordinal%3 else 3
        self.smoke_head=(ordinal+1)%SMOKE_SLOTS
        self.next_smoke=now+(1/6 if self.fast else 1/3)

    @staticmethod
    def _paste(frame,sprite,x,y):
        if sprite is not None:
            frame.alpha_composite(sprite,(round(x-sprite.width/2),round(y-sprite.height/2)))

    def draw(self, frame):
        """Only cached sprites and arithmetic. Draw BEFORE the character silhouette."""
        now=self.now;keep=TRAIL_SAMPLES if self.fast else 6
        for index,track in enumerate(self.trails):
            head=self.heads[index]
            for offset in range(keep-1,-1,-1):
                slot=track[(head-1-offset)%TRAIL_SAMPLES]
                age=now-slot[3]
                if 0<=age<.82:
                    level=(1-age/.82)*(.45+.18*slot[2])
                    alpha=min(len(ALPHAS)-1,int(level*(len(ALPHAS)-1)))
                    self._paste(frame,self.sprites[(index+offset)%4][alpha],slot[0],slot[1])
        for slot in self.smoke:
            age=now-slot[0]
            if not 0<=age<1.25:
                continue
            level=min(1.,age/.15)*max(0.,1-age/1.25)*.85
            alpha=min(len(ALPHAS)-1,int(level*(len(ALPHAS)-1)))
            sprite=self.sprites[int(slot[4])][alpha]
            if sprite is None:
                continue
            # Entire sprite starts above the apex, including its baked halo.
            y=slot[2]-3*self.scale-sprite.height/2-age*8*self.scale
            x=slot[1]+slot[3]+math.sin(age*2.2)*1.1*self.scale
            self._paste(frame,sprite,x,y)

    def stats(self):
        trail=sum(0<=self.now-s[3]<.82 for track in self.trails for s in track)
        smoke=sum(0<=self.now-s[0]<1.25 for s in self.smoke)
        return dict(trail=trail,smoke=smoke,total=trail+smoke+3,cap=MAX_PARTICLES,
                    thinking=self.thinking,quality='full' if self.fast else 'reduced')
