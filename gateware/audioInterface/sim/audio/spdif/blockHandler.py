from torii.sim import Settle
from torii.test import ToriiTestCase

from ....audio.spdif.blockHandler import BlockHandler

class BlockHandlerTestCase(ToriiTestCase):
	dut : BlockHandler = BlockHandler
	domains = (('usb', 60e6), )

	def computeParity(self, data):
		parity = 0
		for bit in range(27):
			parity ^= (data >> bit) & 1
		return parity << 27

	@ToriiTestCase.simulation
	@ToriiTestCase.sync_domain(domain = 'usb')
	def testBlockHandling(self):
		channel = self.dut.channel
		dataIn = self.dut.dataIn
		dataAvailable = self.dut.dataAvailable
		blockBeginning = self.dut.blockBeginning
		blockComplete = self.dut.blockComplete
		dropBlock = self.dut.dropBlock

		channelStatusBytes = [
			# S/PDIF, PCM audio, mode 0
			0b00000000,
			# Category 0
			0b00000000,
			# Source 1, Channel 1
			0b00010001,
			# 48kHz, high accuracy clock
			0b00010010,
			# 16-bit samples, resampled from 44.1kHz
			0b11110010,
			# 19 unused bytes follow
			0, 0, 0, 0,
			0, 0, 0, 0,
			0, 0, 0, 0,
			0, 0, 0, 0,
			0, 0, 0
		]

		yield
		yield from self.pulse_pos(blockBeginning)
		for sample in range(192):
			statusBit = (channelStatusBytes[sample >> 3] >> (sample & 3)) & 1
			# Channel A
			sampleA = ((0xca00 | sample) << 8) | (statusBit << 26)
			sampleA |= self.computeParity(sampleA)
			yield dataIn.eq(sampleA)
			yield channel.eq(0)
			yield from self.pulse_pos(dataAvailable)
			# Channel B
			sampleB = ((0xcb00 | sample) << 8) | (statusBit << 26)
			sampleB |= self.computeParity(sampleB)
			yield dataIn.eq(sampleB)
			yield channel.eq(1)
			yield from self.pulse_pos(dataAvailable)
		yield from self.pulse_pos(blockComplete)
		yield from self.step(192)
		yield

# 0x1f00d00
# 0x1cafe00
