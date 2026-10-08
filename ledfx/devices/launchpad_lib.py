#
# Hack and slashed down from original lib, to remove pygame
# remove all LED manipulations as LEDFX does this in single message
# generally remove lint problems
#
# A Novation Launchpad control suite for Python.
#
# https://github.com/FMMT666/launchpad.py
#
# FMMT666(ASkr) 01/2013..09/2019..08/2020..01/2021
# www.askrprojects.net

import array
import logging
import time
import timeit
from typing import ClassVar

import rtmidi
from rtmidi import SystemError as RtmidiSystemError
from rtmidi.midiutil import open_midiinput, open_midioutput

_LOGGER = logging.getLogger(__name__)

# This code is not hardened for device not present or device removal
# in all cases it will be necassary to restart ledfx to recover


class RtmidiWrap:
    apis: ClassVar[dict[int, str]] = {
        rtmidi.API_MACOSX_CORE: "macOS (OS X) CoreMIDI",
        rtmidi.API_LINUX_ALSA: "Linux ALSA",
        rtmidi.API_UNIX_JACK: "Jack Client",
        rtmidi.API_WINDOWS_MM: "Windows MultiMedia",
        rtmidi.API_RTMIDI_DUMMY: "RtMidi Dummy",
    }

    # -- init
    def __init__(self):
        self.devIn = None
        self.devOut = None
        self.nameIn = None
        self.nameOut = None

    def SearchDevices(self, name, output=True, input=True, quiet=True):
        ret = []
        available_apis = rtmidi.get_compiled_api()

        for api, api_name in sorted(self.apis.items()):
            if api in available_apis:
                if output:
                    try:
                        midi = rtmidi.MidiOut(api)
                        ports = midi.get_ports()
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.warning("Could not probe MIDI ouput ports: %s", exc)
                        continue
                    for port, pname in enumerate(ports):
                        _LOGGER.debug("SearchDevices: %s %s", port, pname)
                        if str(pname.lower()).find(name.lower()) >= 0:
                            _LOGGER.debug("%s %s", port, pname)
                            ret.append(port)
                if input:
                    try:
                        midi = rtmidi.MidiIn(api)
                        ports = midi.get_ports()
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.warning("Could not probe MIDI input ports: %s", exc)
                        continue
                    for port, pname in enumerate(ports):
                        if str(pname.lower()).find(name.lower()) >= 0:
                            _LOGGER.debug("%s %s", port, pname)
                            ret.append(port)
                del midi

        return ret

    def SearchDevice(self, name, output=True, input=True, number=0):
        ret = self.SearchDevices(name, output, input)

        if number < 0 or number >= len(ret):
            return None

        return ret[number]

    def OpenOutput(self, midi_id):
        if self.devOut is None:
            try:
                self.devOut, self.nameOut = open_midioutput(midi_id, interactive=False)
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("%s", e)
                self.devOut = None
                self.nameOut = None
                return False
        return True

    def CloseOutput(self):
        if self.devOut is not None:
            self.devOut.close_port()
            del self.devOut
            self.devOut = None
            self.nameOut = None

    def OpenInput(self, midi_id):
        if self.devIn is None:
            try:
                self.devIn, self.nameIn = open_midiinput(midi_id, interactive=False)
            except Exception:  # noqa: BLE001
                self.devIn = None
                self.nameIn = None
                return False
        return True

    def CloseInput(self):
        if self.devIn is not None:
            self.devIn.close_port()
            del self.devIn
            self.devIn = None
            self.nameIn = None

    def RawWriteSysEx(self, lstMessage):
        self.devOut.send_message(
            array.array("B", [0xF0] + lstMessage + [0xF7]).tobytes()
        )

    def ReadRaw(self):
        result = self.devIn.get_message()
        if result:
            return result[0]
        else:
            return None

    # -- sends a single, short message
    def RawWrite(self, stat, dat1, dat2):
        self.devOut.send_message([stat, dat1, dat2])

    # -- sends a running status 2 byte message MADNESS
    def RawWriteTwo(self, dat1, dat2):
        self.devOut.send_message([dat1, dat2])


class LaunchpadBase:
    # these are defaults that need to be overridden in inheriting classes
    layout: ClassVar[dict[str, int]] = {"pixels": 0, "rows": 0}
    segments: ClassVar[list[tuple[str, str, list[list[int]], int]]] = []
    # end defaults

    def __init__(self):
        self.midi = RtmidiWrap()  # midi interface instance (singleton)
        self.idOut = None
        self.idIn = None
        self.lasttime = 0
        self.frame = 0
        self.fps = 0
        self.do_once = True
        self.supported = False

    def flush(self, data, alpha, diag):
        if self.do_once:
            _LOGGER.warning("flush not implemented for %s", self.__class__.__name__)
            self.do_once = False
        return False

    def __del__(self):
        self.Close()

    # -- Opens one of the attached Launchpad MIDI devices.
    def Open(self, number=0, name="Launchpad"):
        self.idOut = self.midi.SearchDevice(name, True, False, number=number)
        self.idIn = self.midi.SearchDevice(name, False, True, number=number)

        if self.idOut is None or self.idIn is None:
            return False

        if self.midi.OpenOutput(self.idOut) is False:
            return False

        return self.midi.OpenInput(self.idIn)

    # -- Checks if a device exists, but does not open it.
    # -- Does not check whether a device is in use or other, strange things...
    def Check(self, number=0, name="Launchpad"):
        self.idOut = self.midi.SearchDevice(name, True, False, number=number)
        self.idIn = self.midi.SearchDevice(name, False, True, number=number)

        return self.idOut is not None and self.idIn is not None

    # -- Closes this device
    def Close(self):
        self.midi.CloseInput()
        self.midi.CloseOutput()

    # -- _LOGGER.info's a list of all devices to the console (for debug)
    def ListAll(self, searchString=""):
        self.midi.SearchDevices(searchString, True, True, False)

    def ButtonFlush(self):
        doReads = 0
        # wait for that amount of consecutive read fails to exit
        while doReads < 3:
            if self.midi.ReadRaw() is None:
                doReads += 1
                time.sleep(0.005)
            else:
                doReads = 0

    # -- Returns a list of all MIDI events, empty list if nothing happened.
    # -- Useful for debugging or checking new devices.
    def EventRaw(self):
        return self.midi.ReadRaw()


class Launchpad(LaunchpadBase):
    # -- Returns the raw value of the last button change as a list:
    # -- [ <button>, <True/False> ]
    def ButtonStateRaw(self):
        a = self.midi.ReadRaw()
        if a is not None:
            return [
                a[1] if a[0] == 144 else a[1] + 96,
                bool(a[2] > 0),
            ]
        else:
            return None

    # -- Returns an x/y value of the last button change as a list:
    # -- [ <x>, <y>, <True/False> ]
    def ButtonStateXY(self):
        a = self.midi.ReadRaw()
        if a is not None:
            if a[0] == 144:
                x = a[1] & 0x0F
                y = (a[1] & 0xF0) >> 4

                return [x, y + 1, bool(a[2] > 0)]
            elif a[0] == 176:
                return [a[1] - 104, 0, bool(a[2] > 0)]
        return None


class LaunchpadPro(LaunchpadBase):
    COLORS: ClassVar[dict[str, int]] = {
        "black": 0,
        "off": 0,
        "white": 3,
        "red": 5,
        "green": 17,
    }

    def Open(self, number=0, name="Pro"):
        retval = super().Open(number=number, name=name)
        if retval is True and name.lower() == "pro":
            # avoid sending this to an Mk2
            self.LedSetMode(0)

        return retval

    def Check(self, number=0, name="Launchpad Pro"):
        return super().Check(number=number, name=name)

    def LedSetLayout(self, mode):
        if mode < 0 or mode > 0x0D:
            return

        self.midi.RawWriteSysEx([0, 32, 41, 2, 16, 34, mode])
        time.sleep(0.010)

    def LedSetMode(self, mode):
        if mode < 0 or mode > 1:
            return

        self.midi.RawWriteSysEx([0, 32, 41, 2, 16, 33, mode])
        time.sleep(0.010)

    def ButtonStateRaw(self, returnPressure=False):
        a = self.midi.ReadRaw()
        if a is not None:
            if returnPressure is False:
                while a[0] == 208:
                    a = self.midi.ReadRaw()
                    if a is None:
                        return None

            if a[0] == 144 or a[0] == 176:
                return [a[1], a[2]]
            else:
                if returnPressure:
                    if a[0] == 208:
                        return [255, a[1]]
                    else:
                        return None
                else:
                    return None
        else:
            return None

    def ButtonStateXY(self, mode="classic", returnPressure=False):
        a = self.midi.ReadRaw()
        if a is not None:
            if returnPressure is False:
                while a[0] == 208:
                    a = self.midi.ReadRaw()
                    if a is None:
                        return None

            if a[0] == 144 or a[0] == 176:
                if mode.lower() != "pro":
                    x = (a[1] - 1) % 10
                else:
                    x = a[1] % 10
                y = (99 - a[1]) // 10

                return [x, y, a[2]]
            else:
                if a[0] == 208:
                    return [255, 255, a[1]]
                else:
                    return None
        else:
            return None


class LaunchpadMk2(LaunchpadPro):
    # -- Opens one of the attached Launchpad MIDI devices.
    # -- Uses search string "Mk2", by default.

    # Mk2 programmers manual
    # https://fael-downloads-prod.focusrite.com/customer/prod/s3fs-public/downloads/Launchpad%20MK2%20Programmers%20Reference%20Manual%20v1.03.pdf

    layout: ClassVar[dict[str, int]] = {"pixels": 81, "rows": 9}
    segments: ClassVar[list[tuple[str, str, list[list[int]], int]]] = [
        ("TopBar", "mdi:table-row", [[72, 79]], 1),
        (
            "RightBar",
            "mdi:table-column",
            [
                [8, 8],
                [17, 17],
                [26, 26],
                [35, 35],
                [44, 44],
                [53, 53],
                [62, 62],
                [71, 71],
            ],
            1,
        ),
        (
            "Matrix",
            "mdi:grid",
            [
                [0, 7],
                [9, 16],
                [18, 25],
                [27, 34],
                [36, 43],
                [45, 52],
                [54, 61],
                [63, 70],
            ],
            8,
        ),
    ]

    def __init__(self):
        super().__init__()
        self.supported = True

    # Overrides "LaunchpadPro" method
    def Open(self, number=0, name="Mk2"):
        return super().Open(number=number, name=name)

    def Check(self, number=0, name="Mk2"):
        return super().Check(number=number, name=name)

    # -- Returns the raw value of the last button change (pressed/unpressed) as a list
    # -- [ <x>, <y>, <value> ], in which <x> and <y> are the buttons coordinates and
    # -- <svalue> the intensity. Because the Mk2 does not come with full analog capabilities,
    # -- unlike the "Pro", the intensity values for the "Mk2" are either 0 or 127.
    # -- 127 = button pressed; 0 = button released
    # -- Notice that this is not (directly) compatible with the original ButtonStateRaw()
    # -- method in the "Classic" Launchpad, which only returned [ <button>, <True/False> ].
    # -- Compatibility would require checking via "== True" and not "is True".
    # Overrides "LaunchpadPro" method
    def ButtonStateXY(self):
        a = self.midi.ReadRaw()
        if a is not None:
            if a[0] == 144 or a[0] == 176:
                if a[1] >= 104:
                    x = a[1] - 104
                    y = 0
                else:
                    x = (a[1] - 1) % 10
                    y = (99 - a[1]) // 10

                return [x, y, a[2]]
            else:
                return None
        else:
            return None

    def flush(self, data, alpha, diag):
        if diag:
            start = timeit.default_timer()

        try:
            # we will use RawWriteSysEx(self, lstMessage, timeStamp=0)
            # this function adds the preamble 240 and post amble 247
            #
            # There is only one layout implied for LEDs:
            #
            # Host => Launchpad MK2:
            # Hex: F0h 00h 20h 29h 02h 18h 08h <colourspec> [<colourspec> […]] F7h
            # Dec: 240 0   32  41  2   24  11  <colourspec> [<colourspec> […]] 247
            #
            # the <colourspec> is structured as follows:
            # - LED index (1 byte)  ---- WARNING, each row starts at 11, 21, 31 etc
            # - Lighting data (1 – 3 bytes)
            # - 3: RGB colour, 3 bytes for Red, Green and Blue 6 bit (63: Max, 0: Min).
            # Final top row starts at 104 for control buttons and is only 8 wide
            #
            # The message may contain up to 80 <colourspec> entries to light up the entire
            # Launchpad Mk2 surface.

            # stuff the send buffer with the command preamble
            send_buffer = [0, 32, 41, 2, 24, 11]

            # prebump the programmer mode index up a row and just before
            pgm_mode_pos = 10
            for idx, pixel in enumerate(data):
                # there is no top right icon, skip it
                if idx >= 80:
                    break
                # check for row bumps
                if idx % 9 == 0:
                    pgm_mode_pos += 1
                # one time correct for top row control buttons index'd at 104
                if pgm_mode_pos == 91:
                    pgm_mode_pos = 104
                send_buffer.extend(
                    [
                        pgm_mode_pos,
                        max(min(int(pixel[0] // 4), 63), 0),
                        max(min(int(pixel[1] // 4), 63), 0),
                        max(min(int(pixel[2] // 4), 63), 0),
                    ]
                )
                pgm_mode_pos += 1
            self.midi.RawWriteSysEx(send_buffer)

        except RuntimeError as e:
            _LOGGER.warning("Flush (%s): %s", type(e).__name__, e)
            return False

        except RtmidiSystemError as e:
            _LOGGER.warning("Flush (%s): %s", type(e).__name__, e)
            return False

        if diag:
            now = timeit.default_timer()
            nowint = int(now)
            # if now just rolled over a second boundary
            if nowint != self.lasttime:
                self.fps = self.frame
                self.frame = 0
            else:
                self.frame += 1
            _LOGGER.debug("Launchpad Mk2 flush %s : %s", self.fps, now - start)
            self.lasttime = nowint

        return True


class LaunchControlXL(LaunchpadBase):
    def Open(self, number=0, name="Control XL", template=1):

        template = min(int(template), 16)  # make int and limit to <=8
        template = max(template, 1)  # no negative numbers

        self.UserTemplate = template

        retval = super().Open(number=number, name=name)
        if retval is True:
            self.TemplateSet(self.UserTemplate)

        return retval

    def Check(self, number=0, name="Control XL"):
        return super().Check(number=number, name=name)

    # -- Sets the layout template.
    # -- 1..8 selects the user and 9..16 the factory setups.
    def TemplateSet(self, templateNum):
        if templateNum < 1 or templateNum > 16:
            return
        else:
            self.UserTemplate = templateNum
            self.midi.RawWriteSysEx([0, 32, 41, 2, 17, 119, templateNum - 1])

    # -- Clears the input buffer (The Launchpads remember everything...)
    def InputFlush(self):
        return self.ButtonFlush()

    def InputStateRaw(self):
        a = self.midi.ReadRaw()
        if a is not None:
            # --- pressed
            if a[0] == 144:
                return [a[1], True, 127]
            # --- released
            elif a[0] == 128:
                return [a[1], False, 0]
            # --- potentiometers and the four cursor buttons
            elif a[0] == 176:
                # --- cursor buttons
                if a[1] >= 104 and a[1] <= 107:
                    if a[2] > 0:
                        return [a[1], True, a[2]]
                    else:
                        return [a[1], False, 0]
                # --- potentiometers
                else:
                    return [a[1], a[2], 0]
            else:
                return None
        else:
            return None


class LaunchControl(LaunchControlXL):
    def Open(self, number=0, name="Control MIDI", template=1):
        self.UserTemplate = template

        retval = super().Open(number=number, name=name)
        if retval is True:
            self.TemplateSet(self.UserTemplate)

        return retval

    def Check(self, number=0, name="Control MIDI"):
        return super().Check(number=number, name=name)

    # -- Sets the layout template.
    # -- 1..8 selects the user and 9..16 the factory setups.
    def TemplateSet(self, templateNum):
        if templateNum < 1 or templateNum > 16:
            return
        else:
            self.midi.RawWriteSysEx([0, 32, 41, 2, 10, 119, templateNum - 1])


class LaunchKeyMini(LaunchpadBase):
    def Open(self, number=0, name="LaunchKey"):
        retval = super().Open(number=number, name=name)
        return retval

    def Check(self, number=0, name="LaunchKey"):
        return super().Check(number=number, name=name)

    def InputStateRaw(self):
        a = self.midi.ReadRaw()
        if a is not None:
            # --- pressed key
            if a[0] == 144:
                return [a[1], True, a[2]]
            # --- released key
            elif a[0] == 128:
                return [a[1], False, 0]
            # --- pressed button
            elif a[0] == 153:
                return [a[1], True, a[2]]
            # --- released button
            elif a[0] == 137:
                return [a[1], False, 0]
            # --- potentiometers and the four cursor buttons
            elif a[0] == 176:
                # --- cursor, track and scene buttons
                if a[1] >= 104 and a[1] <= 109:
                    if a[2] > 0:
                        return [a[1], True, 127]
                    else:
                        return [a[1], False, 0]
                # --- potentiometers
                else:
                    return [a[1], a[2], 0]
            else:
                return None
        else:
            return None

    # -- Clears the input buffer (The Launchpads remember everything...)
    def InputFlush(self):
        return self.ButtonFlush()


class Dicer(LaunchpadBase):
    def Open(self, number=0, name="Dicer"):
        retval = super().Open(number=number, name=name)
        return retval

    def Check(self, number=0, name="Dicer"):
        return super().Check(number=number, name=name)

    def ButtonStateRaw(self):
        a = self.midi.ReadRaw()
        if a is not None:
            # --- button on master
            if a[0] >= 154 and a[0] <= 156:
                butNum = a[1]
                if butNum >= 60 and butNum <= 69:
                    butNum -= 59
                    butNum += 10 * (a[0] - 154)
                    if a[2] == 127:
                        return [butNum, True, 127]
                    else:
                        return [butNum, False, 0]
                else:
                    return None
            # --- button on master
            elif a[0] >= 157 and a[0] <= 159:
                butNum = a[1]
                if butNum >= 60 and butNum <= 69:
                    butNum -= 59
                    butNum += 100 + 10 * (a[0] - 157)
                    if a[2] == 127:
                        return [butNum, True, 127]
                    else:
                        return [butNum, False, 0]
                else:
                    return None
        else:
            return None

    # -- Sets the Dicer <device> (0=master, 1=slave) to one of its six modes,
    # -- as specified by <mode>:
    # --  0 - "cue"
    # --  1 - "cue, shift lock"
    # --  2 - "loop"
    # --  3 - "loop, shift lock"
    # --  4 - "auto loop"
    # --  5 - "auto loop, shift lock"
    # --  6 - "one page"
    def ModeSet(self, device, mode):
        if device < 0 or device > 1:
            return

        if mode < 0 or mode > 6:
            return

        self.midi.RawWrite(186 if device == 0 else 189, 17, mode)


class LaunchpadLPX(LaunchpadPro):
    # 	COLORS = {'black':0, 'off':0, 'white':3, 'red':5, 'green':17 }

    layout: ClassVar[dict[str, int]] = {"pixels": 81, "rows": 9}
    segments: ClassVar[list[tuple[str, str, list[list[int]], int]]] = [
        ("TopBar", "mdi:table-row", [[72, 79]], 1),
        ("Logo", "launchpad", [[80, 80]], 1),
        (
            "RightBar",
            "mdi:table-column",
            [
                [8, 8],
                [17, 17],
                [26, 26],
                [35, 35],
                [44, 44],
                [53, 53],
                [62, 62],
                [71, 71],
            ],
            1,
        ),
        (
            "Matrix",
            "mdi:grid",
            [
                [0, 7],
                [9, 16],
                [18, 25],
                [27, 34],
                [36, 43],
                [45, 52],
                [54, 61],
                [63, 70],
            ],
            8,
        ),
    ]

    device_id = 12

    def __init__(self):
        super().__init__()
        self.supported = True

    # Overrides "LaunchpadPro" method
    def Open(self, number=0, name="AUTO"):
        nameList = ["Launchpad X", "LPX"]
        if name != "AUTO":
            # mhh, better not this way
            # nameList.insert( 0, name )
            nameList = [name]
        for name in nameList:  # noqa: PLR1704
            rval = super().Open(number=number, name=name)
            if rval:
                self.LedSetMode(1)
                return rval
        return False

    def Check(self, number=0, name="AUTO"):
        nameList = ["Launchpad X", "LPX"]
        if name != "AUTO":
            # mhh, better not this way
            # nameList.insert( 0, name )
            nameList = [name]
        for name in nameList:  # noqa: PLR1704
            rval = super().Check(number=number, name=name)
            if rval:
                return rval
        return False

    def LedSetLayout(self, mode):
        ValidModes = [0x00, 0x01, 0x04, 0x05, 0x06, 0x07, 0x0D, 0x7F]
        if mode not in ValidModes:
            return

        self.midi.RawWriteSysEx([0, 32, 41, 2, self.device_id, 0, mode])

        time.sleep(0.010)

    def LedSetMode(self, mode):
        if mode < 0 or mode > 1:
            return

        self.midi.RawWriteSysEx([0, 32, 41, 2, self.device_id, 14, mode])
        time.sleep(0.010)

    # -- Sets the button layout to "Session" mode.
    # TODO: ASkr, Undocumented!
    def LedSetButtonLayoutSession(self):
        self.LedSetLayout(0)

    def ButtonStateRaw(self, returnPressure=False):
        a = self.midi.ReadRaw()
        if a is not None:
            # Copied over from the Pro's method.
            # Try to avoid getting flooded with pressure events
            if returnPressure is False:
                while a[0] == 160:
                    a = self.midi.ReadRaw()
                    if a is None:
                        return None

            if a[0] == 144 or a[0] == 176:
                return [a[1], a[2]]
            else:
                if returnPressure:
                    if a[0] == 160:
                        # the X returns button number AND pressure value
                        # adding 255 to make it possible to distinguish "pressed" from "pressure"
                        return [255 + a[1], a[2]]
                    else:
                        return None
                else:
                    return None
        else:
            return None

    def ButtonStateXY(self, mode="classic", returnPressure=False):
        a = self.midi.ReadRaw()
        if a is not None:
            if returnPressure is False:
                while a[0] == 160:
                    a = self.midi.ReadRaw()
                    if a is None:
                        return None

            if a[0] == 144 or a[0] == 176 or a[0] == 160:
                if mode.lower() != "pro":
                    x = (a[1] - 1) % 10
                else:
                    x = a[1] % 10
                # flipped Y axis to match logical fill order of LEDs
                y = (a[1] // 10) - 1

                # now with pressure events (9/2020)
                if a[0] == 160 and returnPressure is True:
                    return [x + 255, y + 255, a[2]]
                else:
                    return [x, y, a[2]]
            else:
                return None
        else:
            return None

    def flush(self, data, alpha, diag):
        if diag:
            start = timeit.default_timer()

        try:
            # we will use RawWriteSysEx(self, lstMessage, timeStamp=0)
            # this function adds the preamble 240 and post amble 247
            #
            # This message can be sent to Lighting Custom Modes and the Programmer mode
            # to light up LEDs. The LED indices used always correspond to those of
            # Programmer mode, regardless of the layout selected:
            #
            # Host => Launchpad X:
            # Hex: F0h 00h 20h 29h 02h 0Ch 03h <colourspec> [<colourspec> […]] F7h
            # Dec: 240 0   32  41  2   12   3  <colourspec> [<colourspec> […]] 247
            #
            # the <colourspec> is structured as follows:
            # - Lighting type (1 byte)
            # - LED index (1 byte)  ---- WARNING, each row starts at 11, 21, 31 etc
            # - Lighting data (1 – 3 bytes)
            # Lighting types:
            # - 0: Static colour from palette 1 byte specifying palette entry.
            # - 1: Flashing colour, 2 bytes specifying Colour B and Colour A.
            # - 2: Pulsing colour, 1 byte specifying palette entry.
            # - 3: RGB colour, 3 bytes for Red, Green and Blue (127: Max, 0: Min).
            #
            # The message may contain up to 81 <colourspec> entries to light up the entire
            # Launchpad X surface.
            # Example:

            # stuff the send buffer with the command preamble
            send_buffer = [0, 32, 41, 2, self.device_id, 3]

            # prebump the programmer mode index up a row and just before
            pgm_mode_pos = 10
            for idx, pixel in enumerate(data):
                # check for row bumps, position is specific to programmer mode
                if idx % 9 == 0:
                    pgm_mode_pos += 1
                send_buffer.extend(
                    [
                        3,
                        pgm_mode_pos,
                        max(min(int(pixel[0] // 2), 127), 0),
                        max(min(int(pixel[1] // 2), 127), 0),
                        max(min(int(pixel[2] // 2), 127), 0),
                    ]
                )
                pgm_mode_pos += 1
            self.midi.RawWriteSysEx(send_buffer)

        except RuntimeError as e:
            _LOGGER.warning("Flush (%s): %s", type(e).__name__, e)
            return False

        except RtmidiSystemError as e:
            _LOGGER.warning("Flush (%s): %s", type(e).__name__, e)
            return False

        if diag:
            now = timeit.default_timer()
            nowint = int(now)
            # if now just rolled over a second boundary
            if nowint != self.lasttime:
                self.fps = self.frame
                self.frame = 0
            else:
                self.frame += 1
            _LOGGER.debug("Launchpad X flush %s : %s", self.fps, now - start)
            self.lasttime = nowint

        return True


class LaunchpadMiniMk3(LaunchpadLPX):
    device_id = 13

    def Open(self, number=0, name="MiniMK3"):
        retval = super().Open(number=number, name=name)
        if retval is True:
            self.LedSetMode(1)

        return retval

    def Check(self, number=0, name="MiniMK3"):
        return super().Check(number=number, name=name)


class MidiFighter64(LaunchpadBase):
    # -- Add some LED mode "constants" for better usability.
    def __init__(self):
        self.MODE_BRIGHT = [i + 18 for i in range(16)]
        self.MODE_TOGGLE = [i + 34 for i in range(8)]
        self.MODE_PULSE = [i + 42 for i in range(8)]
        self.MODE_ANIM_SQUARE = 50
        self.MODE_ANIM_CIRCLE = 51
        self.MODE_ANIM_STAR = 52
        self.MODE_ANIM_TRIANGLE = 53

        super().__init__()

    def Open(self, number=0, name="Fighter 64"):
        return super().Open(number=number, name=name)

    def Check(self, number=0, name="Fighter 64"):
        return super().Check(number=number, name=name)

    # -- Controls a the mode of a grid LED by its <number> and the mode <mode> of the LED.
    # --  <number> 36..99
    # --  <mode>   18..53 for brightness, toggling and animation
    # -- Internal LED numbers are 3 octaves lower than the color numbers.
    # -- The mode must be sent over channel 4
    def LedCtrlRawMode(self, number, mode):
        # uses the original button numbers for usability
        if number < 36 or number > 99:
            return
        if mode < 18 or mode > 53:
            return

        self.midi.RawWrite(147, number - 3 * 12, mode)

    def ButtonStateRaw(self):
        a = self.midi.ReadRaw()
        if a is not None:
            # Mhh, I guess it's about time to think about adding MIDI channels, isn't it?
            # But for now, we just check ch 2 and 3:
            if a[0] == 145 or a[0] == 146:
                return [a[1], a[2]]
            else:
                if a[0] == 130 or a[0] == 129:
                    return [a[1], 0]
                else:
                    return None
        else:
            return None

    def ButtonStateXY(self):
        a = self.midi.ReadRaw()
        if a is not None:
            # whatever that is, does not belong here...
            if a[1] < 36 or a[1] > 99:
                return None

            x = (a[1] - 36) % 4
            if a[1] >= 68:
                x += 4
            y = 7 - ((a[1] - 36) % 32) // 4

            if a[0] == 145 or a[0] == 146:
                return [x, y, a[2]]
            else:
                if a[0] == 130 or a[0] == 129:
                    return [x, y, 0]
                else:
                    return None
        else:
            return None


class LaunchpadProMk3(LaunchpadPro):
    def Open(self, number=0, name="ProMk3"):
        retval = super().Open(number=number, name=name)
        if retval is True:
            # enable Programmer's mode
            self.LedSetMode(1)
        return retval

    def Check(self, number=0, name="ProMk3"):
        return super().Check(number=number, name=name)

    def LedSetMode(self, mode):
        if mode < 0 or mode > 1:
            return

        self.midi.RawWriteSysEx([0, 32, 41, 2, 14, 14, mode])
        time.sleep(0.1)

    def ButtonStateXY(self, mode="classic", returnPressure=False):
        a = self.midi.ReadRaw()
        if a is not None:
            # 8/2020: Try to mitigate too many pressure events that a bit (yep, seems to work fine!)
            # 9/2020: XY now also with pressure event functionality
            if returnPressure is False:
                while a[0] == 208:
                    a = self.midi.ReadRaw()
                    if a is None:
                        return None

            if a[0] == 144 or a[0] == 176:
                if mode.lower() != "pro":
                    x = (a[1] - 1) % 10
                else:
                    x = a[1] % 10
                if a[1] > 99:
                    y = 9
                elif a[1] < 10:
                    y = 10
                else:
                    y = (99 - a[1]) // 10

                return [x, y, a[2]]
            else:
                # TOCHK: this should be safe without checking "returnPressure"
                if a[0] == 208:
                    return [255, 255, a[1]]
                else:
                    return None
        else:
            return None

    # -- Go back to custom modes before closing connection
    # -- Otherwise Launchpad will stuck in programmer mode
    def Close(self):
        # re-enter Live mode
        if self.midi.devIn is not None and self.midi.devOut is not None:
            self.LedSetMode(0)


class LaunchpadS(LaunchpadPro):
    layout: ClassVar[dict[str, int]] = {"pixels": 81, "rows": 9}
    segments: ClassVar[list[tuple[str, str, list[list[int]], int]]] = [
        ("TopBar", "mdi:table-row", [[72, 79]], 1),
        (
            "RightBar",
            "mdi:table-column",
            [
                [8, 8],
                [17, 17],
                [26, 26],
                [35, 35],
                [44, 44],
                [53, 53],
                [62, 62],
                [71, 71],
            ],
            1,
        ),
        (
            "Matrix",
            "mdi:grid",
            [
                [0, 7],
                [9, 16],
                [18, 25],
                [27, 34],
                [36, 43],
                [45, 52],
                [54, 61],
                [63, 70],
            ],
            8,
        ),
    ]

    # this maps pixels from physical bottom left to launchpad references
    # as it is explicit per pixel
    # fmt: off
    pixel_map: ClassVar[list[int]] = [112, 113, 114, 115, 116, 117, 118, 119, 120,
                 96, 97, 98, 99, 100, 101, 102, 103, 104,
                 80, 81, 82, 83, 84, 85, 86, 87, 88,
                 64, 65, 66, 67, 68, 69, 70, 71, 72,
                 48, 49, 50, 51, 52, 53, 54, 55, 56,
                 32, 33, 34, 35, 36, 37, 38, 39, 40,
                 16, 17, 18, 19, 20, 21, 22, 23, 24,
                 0, 1, 2, 3, 4, 5, 6, 7, 8,
                 104, 105, 106, 107, 108, 109, 110, 111, 112]
    # fmt: on

    # this maps launchpad pixels from bottom left to source from data
    # as plotting is order driven via a complex mapping of

    # Starting at the top-left-hand corner in either mode, subsequent
    # note messages update the 64-pad grid horizontally and then
    # vertically. They then update the eight clip launch buttons, and
    # then the eight mode buttons.

    # fmt: off
    pixel_map2: ClassVar[list[int]] = [63, 64, 65, 66, 67, 68, 69, 70,
                  54, 55, 56, 57, 58, 59, 60, 61,
                  45, 46, 47, 48, 49, 50, 51, 52,
                  36, 37, 38, 39, 40, 41, 42, 43,
                  27, 28, 29, 30, 31, 32, 33, 34,
                  18, 19, 20, 21, 22, 23, 24, 25,
                  9, 10, 11, 12, 13, 14, 15, 16,
                  0, 1, 2, 3, 4, 5, 6, 7,
                  71, 62, 53, 44, 35, 26, 17, 8,
                  72, 73, 74, 75, 76, 77, 78, 79]
    # fmt: on

    buffer0 = True

    def __init__(self):
        super().__init__()
        self.supported = True

    def Open(self, number=0, name="Launchpad S"):
        retval = super().Open(number=number, name=name)
        if retval is True:
            _LOGGER.info("Launchpad S ready")
            # no mode set required, at least nothing in the manual
        # try and clear the leds
        self.midi.RawWrite(0xB0, 0x00, 0x00)
        return retval

    def LedSetLayout(self, mode):
        _LOGGER.error("LedSetLayout for Launchpad S has not been implemented")

    def LedSetMode(self, mode):
        _LOGGER.error("LedSetMode for Launchpad S has not been implemented")

    def LedSetButtonLayoutSession(self):
        _LOGGER.error(
            "LedSetButtonLayoutSession for Launchpad S has not been implemented"
        )

    def ButtonStateRaw(self, returnPressure=False):
        _LOGGER.error("ButtonStateRaw for Launchpad S has not been implemented")

    def ButtonStateXY(self, mode="classic", returnPressure=False):
        _LOGGER.error("ButtonStateXY for Launchpad S has not been implemented")

    def scolmap(self, r, g):
        if r > 191.0:
            out = 0x0F
        elif r > 127.0:
            out = 0x0E
        elif r > 63.0:
            out = 0x0D
        else:
            out = 0x0C

        if g > 191.0:
            out |= 0x30
        elif g > 127.0:
            out |= 0x20
        elif g > 63.0:
            out |= 0x10

        return out

    def flush(self, data, alpha, diag):
        # https://www.bhphotovideo.com/lit_files/88417.pdf
        # how to do channels in rtmidi
        # https://github.com/SpotlightKid/python-rtmidi/issues/38

        # 92 is Note on, channel 3 ( 3 - 1) followed by 2 color pixel data bytes
        # pixel data = 0x0C | 0x30 green | 0x03 red
        # code now supports running mode where status byte is only sent at
        # start of frame
        if diag:
            start = timeit.default_timer()

        send_status = True

        try:
            for index, map in enumerate(self.pixel_map2):
                if (index % 2) == 0:
                    out1 = self.scolmap(data[map][0], data[map][1])
                else:
                    out2 = self.scolmap(data[map][0], data[map][1])

                    if alpha:
                        if send_status:
                            self.midi.RawWrite(0x92, out1, out2)
                            send_status = False
                        else:
                            self.midi.RawWriteTwo(out1, out2)
                    else:
                        self.midi.RawWrite(0x92, out1, out2)

            if self.buffer0:
                # Display buffer 0, and write to buffer 1
                self.midi.RawWrite(0xB0, 0x00, 0x24)
            else:
                # Display buffer 1, and write to buffer 0
                self.midi.RawWrite(0xB0, 0x00, 0x21)

            # and flip buffers
            self.buffer0 = not self.buffer0

        except RuntimeError as e:
            _LOGGER.warning("Flush (%s): %s", type(e).__name__, e)
            return False

        except RtmidiSystemError as e:
            _LOGGER.warning("Flush (%s): %s", type(e).__name__, e)
            return False

        if diag:
            now = timeit.default_timer()
            nowint = int(now)
            # if now just rolled over a second boundary
            if nowint != self.lasttime:
                self.fps = self.frame
                self.frame = 0
            else:
                self.frame += 1
            _LOGGER.debug("Launchpad S flush %s : %s", self.fps, now - start)
            self.lasttime = nowint

        return True
