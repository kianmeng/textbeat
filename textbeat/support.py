from .defs import *
from shutilwhich import which
import tempfile, shutil
from . import instrument
# from xml.dom import minidom
ARGS = get_args()
SUPPORT = set(['midi'])
SUPPORT_ALL = set(['carla', 'midi', 'fluidsynth', 'soundfonts']) # gme,mpe,sonicpi,supercollider,csound
MIDI = True
SOUNDFONTS = False # TODO: make this a SupportPlugin ref
AUTO = False
auto_inited = False

SUPPORT_PLUGINS = {}

# load plugins from plugins dir

import textbeat.plugins as tbp
from textbeat.plugins import *
# search module exports for plugins
plugs = []
for p in tbp.__dict__:
    try:
        pattr = getattr(tbp, p)
        plugs += [pattr.export()]
    except:
        pass
# plugs = instrument.plugins()
for plug in plugs:
    # plug.init()
    ps = plug.support()
    SUPPORT_ALL = SUPPORT_ALL.union(ps)
    if not plug.supported():
        continue
    for s in ps:
        SUPPORT.add(s)
        SUPPORT_PLUGINS[s] = plug
        if 'auto' in s:
            AUTO = True
            auto_inited = True
        if 'soundfonts' in s:
            SOUNDFONTS = True

# Note: the plugins below are old-style (contained within this file).  New style
#   plugins are in the plugins folder and are loaded above

SUPPORT_ALL.add('carla')
if which('carla'):
    SUPPORT.add('carla')
    SUPPORT.add('auto') # auto generate
    AUTO = True
    auto_inited = True

# try:
#     import psonic
#     SUPPORT.add('sonicpi')
# except ImportError:
#     pass

# try:
#     SUPPORT_ALL.add('fluidsynth')
#     if which('fluidsynth'):
#         import fluidsynth # https://github.com/flipcoder/pyfluidsynth
#         SUPPORT.add('fluidsynth')
#         SUPPORT.add('soundfonts')
#         SOUNDFONTS = True
# # except AttributeError:
# #     error("pyFluidSynth AttributeError detected. Use this pyFluidSynth version: https://github.com/flipcoder/pyfluidsynth")
# except ImportError:
#     pass

csound = None
# if which('csound'):
SUPPORT_ALL.add('csound')
try:
    import csnd6
    SUPPORT.add('csound')
except ImportError:
    pass

def supports(dev):
    global SUPPORT
    return dev in SUPPORT

csound_inited = False
def csound_init(gen=[]):
    global csound_inited
    if not csound_inited:
        import subprocess
        csound_proc = subprocess.Popen(['csound', '-odac', '--port='+str(CSOUND_PORT)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        csound = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    csound_inited = True

carla_inited = False
carla_proc = None
carla_temp_proj = None
def carla_init(gen):
    global carla_proc
    global carla_temp_proj
    global carla_inited
    global carla_temp
    
    if not carla_proc:
        import oscpy
        fn = ARGS['SONGNAME']
        if not fn:
            fn = 'default'
        if gen:
            carla_temp_proj = tempfile.mkstemp('.carxp',fn)
            os.close(carla_temp_proj[0])
            carla_temp_proj = carla_temp_proj[1]
            os.unlink(carla_temp_proj)
            base_proj = os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__)),'presets','default.carxp'))
            shutil.copy2(base_proj, carla_temp_proj)

            # add instruments to temp proj file
            filebuf = ''
            with open(carla_temp_proj,'r') as f:
                filebuf = f.read()
            instrumentxml = ''
            i = 0
            for instrument in gen:
                fnparts = instrument.split('.')
                name = fnparts[0]
                try:
                    ext = fnparts[1].upper()
                except IndexError:
                    ext = 'LV2'
                instrumentxml += '<!--'+name+'-->\n'+\
                    '<Plugin><Info>\n'+\
                    '<Type>'+ext+'</Type>\n'+\
                    '<Name>'+name+'</Name>\n'+\
                    '<URI>x</URI>'+\
                    '</Info>\n'+\
                    '<Data>\n'+\
                        '<ControlChannel>N</ControlChannel>\n'+\
                        '<Active>Yes</Active>\n'+\
                        '<Options>'+hex(i)+'</Options>\n'+\
                    '</Data>'+\
                    '</Plugin>\n\n'
                i += 1
            filebuf = filebuf.replace('</EngineSettings>', '</EngineSettings>'+instrumentxml)
            with open(carla_temp_proj,'w') as f:
                f.write(filebuf)
            
            proj = carla_temp_proj
        else:
            proj = fn.split('.')[0]+'.carxp'
        if os.path.exists(proj):
            log(proj)
            carla_proc = subprocess.Popen(['carla',proj], stdout=subprocess.PIPE, stderr=subprocess.PIPE) # '--nogui', 
        elif not gen:
            log('To load a Carla project headless, create a \'%s\' file.' % proj)
    carla_inited = True

def auto_init(gen):
    carla_init(gen)

support_init = {
    'csound': csound_init,
    'carla': carla_init,
    'auto': auto_init,
}

def csound_send(s):
    assert csound
    return csound.sendto(s,('localhost',CSOUND_PORT))

# Currently not used, caches text to speech stuff in a way compatible with jack
# current super slow, need to write stabilizer first
class BackgroundProcess(object):
    def __init__(self, con):
        self.con = con
        self.words = {}
        self.processes = []
    def cache(self,word):
        try:
            tmp = self.words[word]
        except:
            tmp = tempfile.NamedTemporaryFile()
            p = subprocess.Popen(['espeak', '\"'+pipes.quote(word)+'\"','--stdout'], stdout=tmp)
            p.wait()
            self.words[tmp.name] = tmp
        return tmp
    def run(self):
        devnull = open(os.devnull, 'w')
        while True:
            msg = self.con.recv()
            # log(msg)
            if msg[0]==BGCMD.SAY:
                tmp = self.cache(msg[1])
                # super slow, better option needed
                self.processes.append(subprocess.Popen(['mpv','-ao','jack',tmp.name],stdout=devnull,stderr=devnull))
            elif msg[0]==BGCMD.CACHE:
                self.cache(msg[1])
            elif msg[0]==BGCMD.QUIT:
                break
            elif msg[0]==BGCMD.CLEAR:
                self.words.clear()
            else:
                log('BAD COMMAND: ' + msg[0])
            self.processses = list(filter(lambda p: p.poll()==None, self.processes))
        self.con.close()
        for tmp in self.words:
            tmp.close()
        for proc in self.processes:
            proc.wait()

def bgproc_run(con):
    proc = BackgroundProcess(con)
    proc.run()

BGPROC = None
# BGPIPE, child = Pipe()
# BGPROC = Process(target=bgproc_run, args=(child,))
# BGPROC.start()

def supports_soundfonts():
    return SOUNDFONTS
def supports_auto():
    return AUTO
def supports(tech):
    return tech in SUPPORT

def support_stop():
    # stop old-style plugins
    global carla_temp_proj
    if carla_temp_proj:
        os.unlink(carla_temp_proj)
    if csound and csound_proc:
        csound_proc.kill()
    if carla_proc:
        carla_proc.kill()
    if BGPROC:
        BGPIPE.send((BGCMD.QUIT,))
        BGPROC.join()

    # stop plugins from plugins folder
    for plug in plugs:
        if plug.inited():
            plug.stop()
    # if gen_inited and carla_proj:
    #     try:
    #         os.remove(carla_proj[1])
    #     except OSError:
    #         pass
    #     except FileNotFoundError:
    #         pass

