# This is a library of ARM/THUMB assembler instruction definitions
__all__ = ['Num', 'List', 'Reg', 'Label', 'Str',
           #'Argument', 'LabelError', 'Instruction',
           'findInstruction']

from struct import pack

###
# Instruction argument types:
# integer, list of arguments, register, label
class Argument(object):
    def match(self, other):
        """ Matches this instance with given obj """
        raise NotImplementedError

class Num(int, Argument):
    """ Just remember initially specified value format """
    def __new__(cls, val=None, bits='any', positive=False):
        if type(val) is str:
            ret = int.__new__(cls, val, 0) # auto determine base
        elif val is None:
            ret = int.__new__(cls, 0)
            ret.bits = bits
            if bits != 'any':
                ret.maximum = 1 << bits
            ret.positive = positive
            return ret
        else:
            ret = int.__new__(cls, val)
        ret.initial = str(val)
        # and for consistency with Reg:
        ret.val = ret
        ret.bits = None
        return ret
    def __repr__(self):
        if self.bits != None:
            if self.bits != 'any': # numeric
                return "%d-bits integer%s" % (self.bits,
                    ", positive" if self.positive else "")
            return "Integer%s" % (", positive" if self.positive else "")
        return str(self.initial)
    def match(self, other):
        if type(other) is not Num:
            return False
        if self.bits != None:
            if self.positive and other < 0:
                return False
            if self.bits != 'any' and abs(other) >= self.maximum:
                return False
            return True
        return other == self
    def part(self, bits, shift=0):
        return (self >> shift) & (2**bits-1)
    class ThumbExpandable(Argument):
        """ Number compatible with ThumbExpandImm function """
        def __init__(self, bits=12):
            self.bits = bits
        def __repr__(self):
            return "ThumbExpandable integer for %s bits"
        def match(self, other):
            def encode(n):
                " Encodes n to thumb-form or raises ValueError if impossible "
                # 11110 i 0 0010 S 1111   0 imm3 rd4 imm8
                if n <= 0xFF: # 1 byte
                    return n
                b1 = n >> 24
                b2 = (n >> 16) & 0xFF
                b3 = (n >> 8) & 0xFF
                b4 = n & 0xFF
                if b1 == b2 == b3 == b4:
                    return (0b11 << 8) + b1
                if b1 == 0 and b3 == 0:
                    return (0b01 << 8) + b2
                if b2 == 0 and b4 == 0:
                    return (0b10 << 8) + b1
                # rotating scheme
                def rol(n, ofs):
                    return ((n << ofs) & 0xFFFFFFFF) | (n >> (32-ofs))
                    # maybe buggy for x >= 1<<32,
                    # but we will not have such values -
                    # see parseNumber above for explanation
                for i in range(0b1000, 32): # lower values will cause autodetermining to fail
                    val = rol(n, i)
                    if (val & 0xFFFFFF00) == 0 and (val & 0xFF) == 0x80 + (val & 0x7F): # correct
                        return ((i << 7) & 0xFFF) + (val & 0x7F)
                raise ValueError
            def the(bits, shift):
                return (val >> shift) & (2**bits-1)
            if type(other) is not Num:
                return False
            if abs(other) > 2**32-1:
                return False # too large
            if other < 0:
                other += 2**32 # convert to positive
            try:
                val = encode(other)
            except ValueError:
                return False
            other.theval = val
            other.the = the
            other.imm8 = val & (2**8-1)
            other.imm3 = (val >> 8) & (2**3-1)
            other.i = val >> 11
            return True

class List(list, Argument):
    def match(self, other):
        if type(other) not in (List, list): # it may be either our specific List obj or plain list
            return False
        if len(self) != len(other):
            return False
        for i,j in zip(self, other):
            if type(i) is not tuple:
                i = (i,) # to be iterable
            for ii in i:
                if ii.match(j):
                    break
            else: # none matched
                return False
        return True

class Reg(int, Argument):
    _regs = {
        'R0': 0, 'R1': 1, 'R2': 2, 'R3': 3,
        'R4': 4, 'R5': 5, 'R6': 6, 'R7': 7, 'WR': 7,
        'R8': 8, 'R9': 9, 'SB': 9,
        'R10': 10, 'SL': 10, 'R11': 11, 'FP': 11,
        'R12': 12, 'IP': 12, 'R13': 13, 'SP': 13,
        'R14': 14, 'LR': 14, 'R15': 15, 'PC': 15,
        'A1':0,'A2':1,'A3':2,'A4':3,
        'V1':4,'V2':5,'V3':6,'V4':7,
        'V5':8,'V6':9,'V7':10,'V8':11,
    }
    @staticmethod
    def lookup(name):
        """
        Tries to convert given register name to its integer value.
        Will raise IndexError if name is invalid.
        """
        return Reg._regs[name.upper()]
    @staticmethod
    def is_reg(name):
        """ Checks whether string is valid register name """
        return name.upper() in Reg._regs
    def __new__(cls, name=None, hi='any'):
        """
        Usage: either Reg('name') or Reg(hi=True/False) or Reg()
        First is a plain register, others are masks
        """
        if not name or name in ['HI','LO']: # pure mask
            if name == 'HI':
                hi = True
            elif name == 'LO':
                hi = False
            mask = hi
            name = "%s register" % (
                "High" if hi else
                "Low" if hi == False else
                "Any")
            val = -1
        else:
            val = Reg.lookup(name)
            mask = None
        ret = int.__new__(cls, val)
        ret.name = name
        ret.mask = mask
        return ret
    def __repr__(self):
        return self.name
    def match(self, other):
        if not type(other) is Reg:
            return False
        if self.mask != None:
            if self.mask == True: # hireg
                return other >= 8
            elif self.mask == False: # loreg
                return other < 8
            else: # any
                return True
        return self == other

class LabelError(Exception):
    """
    This exception is raised when label requested is not found in given context.
    """
    pass
class Label(Argument):
    def __init__(self, name=None):
        self.name = name
    def __repr__(self):
        return (":%s"%self.name) if self.name else "Label"
    def match(self, other):
        return type(other) is Label
    def getAddress(self, instr):
        if not self.name:
            raise LabelError("This is a mask, not label!")
        try:
            return instr.findLabel(self)
        except IndexError:
            raise LabelError
    def _getOffset(self, instr):
        return self.getAddress(instr) - (instr.getAddr()+4)
    def offset(self, instr, bits):
        """
        Returns offset from given instruction to this label.
        bits - maximum bit-width for offset;
            if offset doesn't fit that width,
            LabelError will be raised.
        This method is intended to be used one time, in non-lambda procs.
        """
        ofs = self._getOffset(instr)
        if abs(ofs) >= (1<<bits):
            raise LabelError("Offset is too far: %X" % ofs)
        if ofs < 0:
            ofs = (1<<bits) + ofs
        return ofs
    def off_s(self, instr, bits, shift):
        """
        Returns `bits' bits of offset, starting from `shift' bit.
        To be used in lambdas.
        Doesn't test maximum width, so consider using off_max!
        Maximum supported offset width is 32 bits.
        """
        if bits+shift > 32:
            raise ValueError("off_s doesn't support "
                             "offset width more than 32 bits! "
                             "bits=%s, shift=%s" % (bits,shift))
        ofs = self.offset(instr, 32) # 32 for negative offsets to be 1-padded
        return (ofs >> shift) & (2**bits-1)
    def off_max(self, instr, bits):
        """
        Tests if offset from given instruction to this label
        fits in `bits' bits.
        Returns 0 on success, for usage in lambdas.
        Raises LabelError on failure.
        """
        self.offset(instr, bits)
        return 0
    def off_pos(self, instr):
        """
        Validates that offset from given instruction to this label
        is positive.
        Returns 0 on success, for usage in lambdas.
        """
        if self._getOffset(instr) < 0:
            raise LabelError("Negative offset not allowed here")
        return 0
    def off_range(self, instr, min, max):
        """
        Tests if offset from given instruction to this label
        fits given range.
        Returns 0 on success, for usage in lambdas.
        Raises LabelError on failure.
        """
        ofs = self._getOffset(instr)
        if ofs < min or ofs > max:
            raise LabelError("Offset %X doesn't fit range %X..%X" % (ofs, min, max))
        return 0
class Str(str, Argument):
    """ This represents _quoted_ string """
    def __new__(cls, val=None):
        if val == None:
            val = "String"
            mask = True
        else:
            mask = False
        ret = str.__new__(cls, val)
        ret.mask = mask
        return ret
    def match(self, other):
        if type(other) is not Str:
            return False
        if self.mask:
            return True
        return self == other

###
# Instructions description
class Instruction(object):
    """
    This class may represent either instruction definition (with masks instead of args)
    or real instruction (with concrete args and context).
    Instruction handler may access its current opcode via self.opcode field.
    """
    def __init__(self, opcode, args, proc, mask=True, pos=None):
        self.opcode = opcode
        self.args = args
        self.proc = proc
        self.mask = mask
        self.pos = pos
        self.size = None
        self.addr = None
        self.original = None
    def __repr__(self):
        ret = "<%s %s>" % (self.opcode, ','.join([repr(x) for x in self.args]))
        if self.original:
            ret += "(mask:%s)" % self.original
        return ret
    def match(self, opcode, args):
        """ Match this definition to given instruction """
        if not self.mask:
            raise ValueError("This is not mask, cannot match")
        # check mnemonic...
        if type(self.opcode) is str:
            if self.opcode != opcode:
                return False
        else: # multiple opcodes possible
            if opcode not in self.opcode:
                return False
        # ... and args
        if len(self.args) != len(args):
            return False
        # __func__ to avoid type checking, as match() will excellently work
        # on plain list.
        if not List.match.__func__(self.args, args):
            return False
        return True
    def instantiate(self, opcode, args, pos):
        if not self.mask:
            raise ValueError("This is not mask, cannot instantiate")
        # this magic is to correctly call constructor of subclass
        ret = self.__class__(opcode, args, self.proc, mask=False, pos=pos)
        if self.size != None:
            ret.size = self.size
        else:
            # this magic is to correctly "replant" custom method to another
            # instance
            import types
            ret.getSize = types.MethodType(self.getSize.__func__, ret)
        ret.original = self
        return ret
    def setAddr(self, addr):
        """
        Sets memory address at which this particular instruction instance resides.
        This is called somewhere after instantiate.
        """
        self.addr = addr
    def getAddr(self):
        " Returns memory address for this instruction "
        return self.addr
    def setBlock(self, block):
        self.block = block
    def findLabel(self, label):
        if label.name in self.block.getContext():
            return self.block.getContext()[label.name]
        if label.name in self.block.patch.context:
            return self.block.patch.context[label.name]
        if label.name in self.block.patch.library.context:
            return self.block.patch.library.context[label.name]
        raise LabelError("Label not found: %s" % repr(label))
    def getCode(self):
        if not self.addr:
            raise ValueError("No address, cannot calculate code")
        if callable(self.proc):
            code = self.proc(self, *self.args)
        else:
            code = self.proc
        if type(code) is str:
            return code
        elif type(code) is int:
            return pack('<H', code)
        elif type(code) is tuple:
            return pack('<HH', code[0], code[1])
        else:
            raise ValueError("Bad code: %s" % repr(code))
    def getSize(self):
        """ default implementation; may be overriden by decorator """
        return self.size
    def getPos(self):
        " pos is instruction's position in patch file "
        return self.pos

class LabelInstruction(Instruction):
    """
    This class represents an abstract label instruction. It has zero size.
    It should be instantiated directly.
    """
    def __init__(self, name, pos, glob=False):
        Instruction.__init__(self, None, [name], None, False, pos)
        self.name = name
        self.glob = glob
    def __repr__(self):
        return "<%slabel:%s>" % ("global " if self.glob else "", self.name)
    def setBlock(self, block):
        self.block = block
        if self.glob:
            block.patch.context[self.name] = self.getAddr()
        else:
            block.getContext()[self.name] = self.getAddr()
    def getSize(self):
        return 0
    def getCode(self):
        return ''
_instructions = []
def instruction(opcode, args, size=2, proc=None):
    """
    This is a function decorator for instruction definitions.
    It may also be used as a plain function, then you should pass it a function as proc arg.
    Note that proc may also be in fact plain value, e.g. for "NOP" instruction.
    """
    def gethandler(proc):
        instr = Instruction(opcode, args, proc)
        if callable(size):
            instr.getSize = size
        else:
            instr.size = size
        _instructions.append(instr)
        return proc
    if proc: # not used as decorator
        gethandler(proc)
    else:
        return gethandler
def instruct_class(c):
    """ decorator for custom instruction classes """
    _instructions.append(c())
    return c

def findInstruction(opcode, args, pos):
    """
    This method tries to find matching instruction
    for given opcode and args.
    On success, it will instantiate that instruction with given pos (cloning that pos).
    On failure, it will throw IndexError.
    """
    for i in _instructions:
        if i.match(opcode, args):
            return i.instantiate(opcode, args, pos.clone())
    raise IndexError("Unsupported instruction: %s" % opcode)

###
# All the instruction definitions
instruction('ADD', [Reg("LO"), Num()], 2, lambda self,rd,imm:
            (1 << 13) + (2 << 11) + (rd << 8) + imm)
instruction('MOV', [Reg("LO"), Reg("LO")], 2, lambda self,rd,rm:
            (0 << 6) + (rm << 3) + rd)
instruction(['MOV','MOVS'], [Reg(), Reg()], 2, lambda self,rd,rm:
            (0b1000110 << 8) + ((rd>>3) << 7) + (rm << 3) + ((rd&0b111) << 0))
instruction(['MOV','MOVS'], [Reg("LO"), Num(bits=8)], 2, lambda self,rd,imm:
            (1 << 13) + (rd << 8) + imm)
instruction(['MOV','MOV.W','MOVS','MOVS.W'], [Reg(), Num.ThumbExpandable()], 4, lambda self,rd,imm:
            (
                (0b11110 << 11) +
                (imm.the(1,11) << 10) +
                (0b10 << 5) +
                ((1 if 'S' in self.opcode else 0) << 4) +
                (0b1111 << 0),
                (imm.the(3,8) << 12) +
                (rd << 8) +
                (imm.the(8,0) << 0)
            ))
instruction(['MOV','MOV.W','MOVW'], [Reg(), Num(bits=16, positive=True)], 4, lambda self,rd,imm:
            (
                (0b11110 << 11) +
                (imm.part(1, 11) << 10) +
                (0b1001 << 6) +
                (imm.part(4, 12)),
                (imm.part(3, 8) << 12) +
                (rd << 8) +
                (imm.part(8))
            ))
def _longJump(self, dest, bl):
    offset = dest.offset(self, 23)
    offset = offset >> 1
    hi_o = (offset >> 11) & (2**11-1)
    lo_o = (offset >> 0)  & (2**11-1)
    hi_c = 0b11110
    lo_c = 0b11111 if bl else 0b10111
    hi = (hi_c << 11) + hi_o
    lo = (lo_c << 11) + lo_o
    return (hi,lo)
instruction('BL', [Label()], 4, lambda self,dest: _longJump(self,dest,True))
instruction('B.W', [Label()], 4, lambda self,dest: _longJump(self,dest,False))
@instruct_class
class DCB(Instruction):
    def __init__(self, opcode=None, args=None, pos=None):
        Instruction.__init__(self, opcode, args, None, pos=pos)
        if args:
            code = ''
            for a in args:
                if type(a) is Str:
                    code += a
                elif type(a) is Num:
                    code += pack('<B', a)
                else:
                    raise ValueError("Bad argument: %s" % repr(a))
            self.code = code
            self.size = len(code)
    def match(self, opcode, args):
        return opcode in ['DCB', 'db']
    def instantiate(self, opcode, args, pos):
        return DCB(opcode, args, pos)
    def getCode(self):
        return self.code
    def getSize(self):
        return len(self.code)
@instruct_class
class ALIGN(Instruction):
    # FIXME handle size properly
    def __init__(self, opcode='ALIGN', args=[(Num(4),Num(2))], proc=None, mask=True, pos=None):
        Instruction.__init__(self, opcode, args, proc, mask, pos)
        if pos: # not mask
            self.size = args[0]
    def getCode(self):
        return '\x00\xBF'*(self.size/2)
    def getSize(self):
        return self.size
instruction('DCH', [Num(bits=16)], 2, lambda self,num: pack('<H', num))
instruction('DCD', [Num(bits=32)], 4, lambda self,num: pack('<I', num))
instruction('NOP', [], 2, 0xBF00)
def Bcond_instruction(cond, val):
    instruction('B'+cond, [Label()], 2, lambda self,lbl:
                (0b1101 << 12) + (val << 8) + (lbl.offset(self,9)>>1))
    instruction('B'+cond+'.W', [Label()], 4, lambda self,lbl:
                (lbl.off_max(self, 19) + # test for maximum

                 (0b11110 << 11) + (lbl.off_s(self,1,18) << 10) +
                    (val << 6) + (lbl.off_s(self,6,12) >> 0),

                 (0b10101 << 11) + (lbl.off_s(self,11,1) >> 0)))
for cond, val in {
    'CC': 0x3, 'CS': 0x2, 'EQ': 0x0, 'GE': 0xA,
    'GT': 0xC, 'HI': 0x8, 'LE': 0xD, 'LS': 0x9,
    'LT': 0xB, 'MI': 0x4, 'NE': 0x1, 'PL': 0x5,
    'VC': 0x7, 'VS': 0x6,
}.items():
    Bcond_instruction(cond, val)
@instruction(['CBZ','CBNZ'], [Reg('LO'), Label()])
def CBx(self, reg, lbl):
    lbl.off_range(self, 0, 126)
    offset = lbl.offset(self, 7) >> 1
    op = 1 if 'N' in self.opcode else 0
    return ((0b1011 << 12) +
            (op << 11) +
            ((offset >> 5) << 9) +
            (1 << 8) +
            ((offset & (2**5-1)) << 3) +
            reg)
instruction('B', [Label()], 2, lambda self,lbl:
            (0b11100 << 11) + (lbl.offset(self, 12)>>1))
@instruct_class
class GlobalLabel(LabelInstruction):
    def __init__(self):
        Instruction.__init__(self, "global", [Label()], None)
    def instantiate(self, opcode, args, pos):
        label = args[0]
        return LabelInstruction(label, pos, glob=True)
