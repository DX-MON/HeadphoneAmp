from enum import IntEnum
from amaranth import Elaboratable, Module, Signal, Array, Cat

__all__ = (
	'I2S',
)

class Channel(IntEnum):
	left = 0
	right = 1

class I2S(Elaboratable):
	def __init__(self):
		# Max division is 12, but because we need to generate both halfs of the clock this is 6.
		self.clkDivider = Signal(range(6))
		self.sampleBits = Signal(range(24))
		self.sample = Array((Signal(24, name = 'sampleL'), Signal(24, name = 'sampleR')))
		self.needSample = Signal()

	def elaborate(self, platform):
		m = Module()
		bus = platform.request('i2s', 0)

		clkCounter = Signal.like(self.clkDivider)
		audioClk = Signal(reset = 1)
		sampleBit = Signal(range(24))
		lastBit = Signal(range(24))
		channelCurrent = Signal(Channel, reset = Channel.left)
		channelNext = Signal(Channel, reset = Channel.right)
		sample = Array(Signal() for i in range(24))

		sampleLatch = Signal()
		m.d.sync += sampleLatch.eq(channelCurrent)
		m.d.comb += self.needSample.eq((~channelCurrent) & sampleLatch)

		with m.FSM():
			with m.State('IDLE'):
				m.d.sync += [
					sampleLatch.eq(0),
					channelCurrent.eq(Channel.left),
					channelNext.eq(Channel.right),
				]
				with m.If((self.sampleBits != 0) & (self.clkDivider != 0)):
					m.d.sync += [
						clkCounter.eq(self.clkDivider),
						sampleBit.eq(self.sampleBits),
						lastBit.eq(self.sampleBits - 1),
					]
					m.next = 'RUN'
			with m.State('RUN'):
				with m.If(clkCounter == self.clkDivider):
					m.d.sync += [
						clkCounter.eq(0),
						audioClk.eq(~audioClk),
					]

					with m.If(audioClk):
						with m.If(sampleBit == self.sampleBits):
							m.d.sync += sampleBit.eq(0)
						with m.Else():
							with m.If(sampleBit == lastBit):
								m.d.sync += channelNext.eq(~channelNext)
							m.d.sync += sampleBit.eq(sampleBit + 1)

						m.d.sync += channelCurrent.eq(channelNext)

				with m.Else():
					m.d.sync += clkCounter.eq(clkCounter + 1)

		m.d.comb += [
			Cat(sample).eq(self.sample[channelCurrent]),
			bus.clk.o.eq(audioClk),
			bus.rnl.o.eq(channelNext),
			bus.data.o.eq(sample[self.sampleBits - sampleBit]),
		]
		return m
