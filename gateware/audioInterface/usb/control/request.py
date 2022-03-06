from amaranth import Module, Signal, Cat
from usb_protocol.types import USBRequestType, USBRequestRecipient
from usb_protocol.types.descriptors.uac3 import AudioClassSpecificRequestCodes, AudioControlInterfaceControlSelectors
from luna.gateware.usb.usb2.request import (
	USBRequestHandler, SetupPacket, StallOnlyRequestHandler, USBInStreamInterface, USBOutStreamInterface
)
from luna.gateware.stream.generator import StreamSerializer
from .deserializer import StreamDeserializer

__all__ = (
	'AudioRequestHandler',
	'StallOnlyRequestHandler',
	'USBRequestType',
	'SetupPacket',
)

class AudioRequestHandler(USBRequestHandler):
	def __init__(self):
		super().__init__()
		# Used to support getting/setting the power state of the device.
		self.powerState = Signal(8)

	def elaborate(self, platform):
		m = Module()
		interface = self.interface
		setup = interface.setup

		rxTriggered = Signal()

		m.submodules.layout1Transmitter = layout1Transmitter = \
			StreamSerializer(data_length = 2, domain = 'usb', stream_type = USBInStreamInterface, max_length_width = 2)
		m.submodules.layout1Receiver = layout1Receiver = \
			StreamDeserializer(dataLength = 2, domain = 'usb', streamType = USBOutStreamInterface, maxLengthWidth = 2)

		with m.If(self.handlerCondition(setup)):
			with m.FSM(domain = 'usb'):
				# IDLE -- no active request being handled
				with m.State('IDLE'):
					# If we've received a new setup packet
					with m.If(setup.received):
						# Switch to the right state for what we need to handle
						with m.Switch(setup.request):
							with m.Case(AudioClassSpecificRequestCodes.CUR):
								m.next = 'HANDLE_CURRENT'
							with m.Default():
								m.next = 'UNHANDLED'
					# Make sure that we reset the rx trigger state
					m.d.usb += rxTriggered.eq(0)
				# HANDLE_CURRENT -- handle a 'CUR' request
				with m.State('HANDLE_CURRENT'):
					# If this is a GET request
					with m.If(setup.is_in_request):
						# Pull the correct setting
						setting, length = self.settingForCurrent(m, setup)
						# Hook up the transmitter ...
						m.d.comb += [
							layout1Transmitter.stream.connect(interface.tx),
							Cat(layout1Transmitter.data).eq(setting),
							layout1Transmitter.max_length.eq(length),
						]
						# ... then trigger it when requested if the lengths match ...
						with m.If(self.interface.data_requested):
							with m.If(setup.length == length):
								m.d.comb += layout1Transmitter.start.eq(1)
							with m.Else():
								m.d.comb += interface.handshakes_out.stall.eq(1)
								m.next = 'IDLE'

						# ... and ACK our status stage.
						with m.If(interface.status_requested):
							m.d.comb += interface.handshakes_out.ack.eq(1)
							m.next = 'IDLE'
					# Else this is a SET request
					with m.Else():
						# Pull the length for the setting
						length = self.lengthForCurrent(m, setup)
						# Hook up the receiver ...
						m.d.comb += [
							interface.rx.connect(layout1Receiver.stream),
							layout1Receiver.maxLength.eq(length),
						]
						# ... trigger the receiver if it isn't yet triggered ...
						with m.If(~rxTriggered):
							with m.If(setup.length == length):
								m.d.comb += layout1Receiver.start.eq(1)
								m.d.usb += rxTriggered.eq(1)
							with m.Else():
								m.d.comb += interface.handshakes_out.stall.eq(1)
								m.next = 'IDLE'
						# ... then when the receiver finishes, write the resulting data to the setting
						with m.Elif(layout1Receiver.done):
							setting = Cat(layout1Receiver.data)
							self.settingFromCurrent(m, setup, setting)

						# If the current out packet is complete and the host is waiting for an ACK, make it
						with m.If(interface.rx_ready_for_response):
							m.d.comb += interface.handshakes_out.ack.eq(1)

						# If we're in the status phase, send a ZLP
						with m.If(interface.status_requested):
							m.d.comb += self.send_zlp()
						# And then deal with the relevant ACK so we can go back to idle
						with m.If(self.interface.handshakes_in.ack):
							m.next = 'IDLE'

				# UNHANDLED -- we've received a request we don't know how to handle
				with m.State('UNHANDLED'):
					# When we next have an opportunity to stall, do so,
					# and then return to idle.
					with m.If(interface.data_requested | interface.status_requested):
						m.d.comb += interface.handshakes_out.stall.eq(1)
						m.next = 'IDLE'

		return m

	def handlerCondition(self, setup : SetupPacket):
		return (
			(setup.type == USBRequestType.CLASS) &
			(setup.recipient == USBRequestRecipient.INTERFACE)
		)

	def lengthForCurrent(self, m : Module, setup : SetupPacket):
		length = Signal(2)
		m.d.comb += length.eq(0)

		# If the request is for the power domain, return the length of the power state setting
		with m.If((setup.index[0:7] == 0) & (setup.index[8:15] == 11) & (setup.value[0:7] == 0) &
			(setup.value[8:15] == AudioControlInterfaceControlSelectors.AC_POWER_DOMAIN_CONTROL)):
			m.d.comb += length.eq(1)

		return length

	def settingForCurrent(self, m : Module, setup : SetupPacket):
		setting = Signal(8)
		m.d.comb += setting.eq(0)

		# If the request is for the power domain, return the power state setting
		with m.If((setup.index[0:7] == 0) & (setup.index[8:15] == 11) & (setup.value[0:7] == 0) &
			(setup.value[8:15] == AudioControlInterfaceControlSelectors.AC_POWER_DOMAIN_CONTROL)):
			m.d.comb += setting.eq(self.powerState)

		return setting, self.lengthForCurrent(m, setup)

	def settingFromCurrent(self, m : Module, setup : SetupPacket, setting : Signal):
		# If the request is for the power domain, return the power state setting
		with m.If((setup.index[0:7] == 0) & (setup.index[8:15] == 11) & (setup.value[0:7] == 0) &
			(setup.value[8:15] == AudioControlInterfaceControlSelectors.AC_POWER_DOMAIN_CONTROL)):
			m.d.usb += self.powerState.eq(setting)
