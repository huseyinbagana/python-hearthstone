from .. import entities
from ..enums import GameTag, PowerType, Zone


def find_unknown_full_entity_in_hand(packets):
	"""
	Finds the first unknown in-hand entity in \a packets list.
	Returns its controller's ID.
	This is the behaviour used before patch 13619 to guess the friendly player.
	"""
	for packet in packets:
		if packet.power_type != PowerType.FULL_ENTITY:
			# We are past the initial FULL_ENTITY block
			return
		tags = dict(packet.tags)
		if tags[GameTag.ZONE] == Zone.HAND and not packet.card_id:
			return tags[GameTag.CONTROLLER]


def find_show_entity(packets):
	"""
	Finds the first SHOW_ENTITY in \a packets list (not in PLAY zone).
	Returns its controller's ID.
	This is the behaviour used as of patch 13619 to guess the friendly player.
	"""
	for packet in packets:
		if packet.power_type == PowerType.SHOW_ENTITY:
			if packet.entity.tags.get(GameTag.ZONE) == Zone.PLAY:
				# Ignore cards already in play (such as enchantments, common in TB)
				continue
			return packet.entity.tags[GameTag.CONTROLLER]
		elif packet.power_type == PowerType.BLOCK_START:
			ret = find_show_entity(packet.packets)
			if ret:
				return ret


class PacketTree:
	def __init__(self, ts):
		self.ts = ts
		self.packets = []
		self.parent = None

	def __iter__(self):
		for packet in self.packets:
			yield packet

	@property
	def start_time(self):
		for packet in self.packets:
			if packet.ts:
				return packet.ts

	@property
	def end_time(self):
		for packet in self.packets[::-1]:
			if packet.ts:
				return packet.ts

	def export(self):
		create_game = self.packets[0]
		game = create_game._export()
		for packet in self.packets[1:]:
			packet._export(game)

		return game

	def guess_friendly_player(self, attempt_old=False):
		"""
		Attempt to guess the friendly player in the game by
		looking for initial unrevealed cards.
		Will not work very early in game initialization and
		produce incorrect results if both hands are revealed.
		\a attempt_old should be True for pre-13619 logs.
		"""
		packets = self.packets[1:]

		if attempt_old:
			# Pre-13619: The first FULL_ENTITY packet which is in Zone.HAND and
			# does *not* have an ID is owned by the friendly player's *opponent*.
			controller = find_unknown_full_entity_in_hand(packets)
			if controller:
				# That controller is the enemy player - return its opponent.
				return controller % 2 + 1

		# Post-13619: The FULL_ENTITY packets no longer contain initial
		# card data, a SHOW_ENTITY always has to happen.
		# The first SHOW_ENTITY packet *will* be the friendly player's.
		return find_show_entity(packets)


class Packet:
	power_type = 0

	def __repr__(self):
		return "<%s>" % (self.__class__.__name__)


class Block(Packet):
	power_type = PowerType.BLOCK_START

	def __init__(self, ts, entity, type, index, effectid, effectindex, target):
		self.ts = ts
		self.entity = entity
		self.type = type
		self.index = index
		self.effectid = effectid
		self.effectindex = effectindex
		self.target = target
		self.ended = False
		self.packets = []

	def __iter__(self):
		for packet in self.packets:
			yield packet

	def __repr__(self):
		return "%s(entity=%r, type=%r, index=%r, target=%r)" % (
			self.__class__.__name__, self.entity, self.type, self.index, self.target
		)

	def end(self):
		self.ended = True

	def _export(self, game):
		for packet in self.packets:
			packet._export(game)


class MetaData(Packet):
	power_type = PowerType.META_DATA

	def __init__(self, ts, meta, data, count):
		self.ts = ts
		self.meta = meta
		self.data = data
		self.count = count
		self.info = []

	def __repr__(self):
		return "%s(meta=%r, data=%r)" % (self.__class__.__name__, self.meta, self.data)

	def _export(self, game):
		pass


class CreateGame(Packet):
	power_type = PowerType.CREATE_GAME

	class Player:
		def __init__(self, ts, id, player_id, hi, lo):
			self.ts = ts
			self.entity = id
			self.player_id = player_id
			self.hi = hi
			self.lo = lo
			self.tags = []

		def _export(self, game):
			player = entities.Player(int(self.entity), self.player_id, self.hi, self.lo)
			game.register_entity(player)
			# TODO player.name
			return player

	def __init__(self, ts, entity):
		self.ts = ts
		self.entity = entity
		self.tags = []
		self.players = []

	def _export(self):
		game = entities.Game(self.entity)
		game.register_entity(game)
		for player in self.players:
			player._export(game)
		return game


class HideEntity(Packet):
	power_type = PowerType.HIDE_ENTITY

	def __init__(self, ts, entity, zone):
		self.ts = ts
		self.entity = entity
		self.zone = zone

	def _export(self, game):
		entity = game.find_entity_by_id(self.entity)
		entity.hide()
		return entity


class FullEntity(Packet):
	power_type = PowerType.FULL_ENTITY

	def __init__(self, ts, entity, card_id):
		self.ts = ts
		self.entity = entity
		self.card_id = card_id
		self.tags = []

	def _export(self, game):
		entity = entities.Card(self.entity, self.card_id)
		entity.tags = dict(self.tags)
		game.register_entity(entity)
		return entity


class ShowEntity(Packet):
	power_type = PowerType.SHOW_ENTITY

	def __init__(self, ts, entity, card_id):
		self.ts = ts
		self.entity = entity
		self.card_id = card_id
		self.tags = []

	def _export(self, game):
		entity = game.find_entity_by_id(self.entity)
		entity.reveal(self.card_id, dict(self.tags))
		return entity


class ChangeEntity(Packet):
	power_type = PowerType.CHANGE_ENTITY

	def __init__(self, ts, entity, card_id):
		self.ts = ts
		self.entity = entity
		self.card_id = card_id
		self.tags = []

	def _export(self, game):
		entity = game.find_entity_by_id(self.entity)
		assert entity, "Attempting CHANGE_ENTITY on entity %r (not found)" % (self.entity)
		entity.change(self.card_id, dict(self.tags))
		return entity


class TagChange(Packet):
	power_type = PowerType.TAG_CHANGE

	def __init__(self, ts, entity, tag, value):
		self.ts = ts
		self.entity = entity
		self.tag = tag
		self.value = value

	def _export(self, game):
		entity = game.find_entity_by_id(self.entity)
		assert entity, "Attempting TAG_CHANGE on entity %r (not found)" % (self.entity)
		entity.tag_change(self.tag, self.value)
		return entity


class Choices(Packet):
	def __init__(self, ts, entity, id, tasklist, type, min, max):
		self.ts = ts
		self.entity = entity
		self.id = id
		self.tasklist = tasklist
		self.type = type
		self.min = min
		self.max = max
		self.source = None
		self.choices = []

	@property
	def player(self):
		return self.entity

	def _export(self, game):
		pass


class SendChoices(Packet):
	def __init__(self, ts, id, type):
		self.ts = ts
		self.entity = None
		self.id = id
		self.type = type
		self.choices = []

	def _export(self, game):
		pass


class ChosenEntities(Packet):
	def __init__(self, ts, entity, id):
		self.ts = ts
		self.entity = entity
		self.id = id
		self.choices = []

	def _export(self, game):
		pass


class Options(Packet):
	def __init__(self, ts, id):
		self.ts = ts
		self.entity = None
		self.id = id
		self.options = []

	def _export(self, game):
		pass


class Option(Packet):
	def __init__(self, ts, entity, id, type, optype):
		self.ts = ts
		self.entity = entity
		self.id = id
		self.type = type
		self.optype = optype
		self.options = []


class SendOption(Packet):
	def __init__(self, ts, option, suboption, target, position):
		self.ts = ts
		self.entity = None
		self.option = option
		self.suboption = suboption
		self.target = target
		self.position = position

	def _export(self, game):
		pass
