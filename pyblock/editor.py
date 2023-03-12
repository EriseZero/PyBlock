"""
Main Code for editing blocks
"""
__author__ = "Alexander Dietz"
__license__ = "MIT"
# pylint: disable=C0103,W1202,E1120,R0913,R0914,E0401,W1203,R1732,W1514,R0912,R0903,R0902,R0911
# pylint: disable=R1716,R0915,R1702

import os
import sys
import copy
import json
import logging
import operator
from pathlib import Path
from collections import OrderedDict
from collections import defaultdict

from PIL import Image
import numpy as np

import pyblock
from pyblock import tools


L = logging.getLogger("pyblock")
L.setLevel(logging.DEBUG)
log_format = logging.Formatter(
    "%(levelname)s  %(asctime)s.%(msecs)03d  %(message)s", "%H%M%S"
)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
handler.setFormatter(log_format)
L.addHandler(handler)


class Editor:
    """Minecraft Editor."""

    def __init__(self, path: str):
        """Initialize the editor with the path to the world.

        Args:
                path: Path to the world folder.
        """
        # Set the world path
        if str(path).endswith("region"):
            self.path = Path(path)
        else:
            self.path = Path(path) / "region"

        # Dict for the blocks to be set
        # key: region index (x,z)
        # value: dict of blocks for this region:
        #        key: chunk coordinates (x,z)
        #        value: list of (block, x, y, z)
        self.blocks_map = {}

        # Dictionary holding local section data for 'get_block'
        self.sections = {}
        self.chunks = {}

        # Dictionary holding local section data for 'set_block'
        self.write_sections = {}
        # self.write_chunks = {}

        # Dictionary to hold entities when copying blocks
        self.entities = {}

    @staticmethod
    def set_verbosity(verbose: int):
        """Sets the verbosity level. Possible values are 0, 1 or 2"""
        level = (logging.WARNING, logging.INFO, logging.DEBUG)[min(verbose, 2)]
        L.setLevel(level)

    def set_block(self, block: pyblock.Block, x: int, y: int, z: int):
        """
        Records position and block to be modified.

        Args:
                block: Minecraft block
                x, y, z: Absolute coordinates
        """
        # Get the region and the chunk coordinates where to set the block
        region_coord, chunk_coord, ylevel, block_index = tools.block_to_id_index(
            x, y, z
        )
        section_id = (region_coord, chunk_coord, ylevel)

        # Create the location to change (block and coordinates inside the chunk)
        change = (block, block_index)

        if section_id in self.blocks_map:
            self.blocks_map[section_id].append(change)
        else:
            self.blocks_map[section_id] = [change]

    def get_block(self, x: int, y: int, z: int) -> pyblock.Block:
        """Returns the block at the given absolute coordinates.

        Args:
            x, y, z: Absolute coordinates
        """
        # Get the ID of the section and the index of the block for that section
        region_coord, chunk_coord, ylevel, block_index = tools.block_to_id_index(
            x, y, z
        )
        section_id = (region_coord, chunk_coord, ylevel)

        # Check if the chunk is already in the local cache
        if section_id not in self.sections:
            section = self.get_section(section_id)
            self.sections[section_id] = section

        # Return the block from the section
        return self.sections[section_id].get_block(block_index)

    def get_section(self, section_id) -> pyblock.Section:
        """Reads a section from file.

        Args:
            section_id: ID of region_index, chunk_index and ylevel
        """
        region_coord, chunk_coord, ylevel = section_id
        chunk_id = (region_coord, chunk_coord)

        # Check if we have read the chunk already
        if chunk_id in self.chunks:
            L.info(f"Cached chunk from region {region_coord} | chunk {chunk_coord}")
            chunk = self.chunks[chunk_id]
        else:
            # return self.chunks[chunk_id].get_section(ylevel)
            L.info(f"Reading chunk from region {region_coord} | chunk {chunk_coord}")

            # Read the region
            region = pyblock.Region(self.path, region_coord)

            # Read the chunk
            chunk = region.read_chunk(chunk_coord)
            self.chunks[chunk_id] = chunk

        # Return the section
        return chunk.get_section(ylevel)


    def copy_blocks(
        self,
        source: list,
        dest: list,
        size: list,
        rep: list = None,
        world_source: str = None,
    ):
        """Copy an area of given size from source to dest (by blocks).

        Args:
            source: x,y,z coordinates of the source.
            dest: x,y,z coordinate of the destination.
            size: x,y,z size of the area top copy
            world_source: Defines the world to copy from. Default is same world.
        """
        if world_source:
            source_world = Editor(world_source)
        else:
            source_world = self

        sx, sy, sz = source
        tx, ty, tz = dest
        wx, wy, wz = size

        for dx in range(wx):
            for dy in range(wy):
                for dz in range(wz):
                    block = source_world.get_block(sx + dx, sy + dy, sz + dz)

                    if rep:
                        for repetition in rep:
                            rx, ry, rz = repetition
                            self.set_block(
                                block, tx + dx + rx, ty + dy + ry, tz + dz + rz
                            )
                    else:
                        self.set_block(block, tx + dx, ty + dy, tz + dz)

        ## Handle the block entities

        # Get the shift for the copy
        shift_x = tx - sx
        shift_y = ty - sy
        shift_z = tz - sz

        # Extract all entities from the source chunks
        self.entities = defaultdict(list)
        for chunk_coord, chunk in source_world.chunks.items():
            for entity in chunk.nbt_data["block_entities"]:
                x = entity["x"].value
                y = entity["y"].value
                z = entity["z"].value

                # Check if the entity is part of the area to copy
                if x >= sx and x < sx + wx:
                    if y >= sy and y < sy + wy:
                        if z >= sz and z < sz + wz:
                            #print("testtest")
                            L.info(
                                f"Found entity of type {entity['id'].value} at {x}/{y}/{z}"
                            )
                            # Modify the destination coordinates
                            x += shift_x
                            y += shift_y
                            z += shift_z

                            # Get coordinates for the destination
                            (
                                region_coord,
                                chunk_coord,
                                _,
                                _,
                            ) = tools.block_to_id_index(x, y, z)
                            key = (region_coord, chunk_coord)

                            # Set the new coordinates for the entity
                            entity["x"].value = x
                            entity["y"].value = y
                            entity["z"].value = z
                            L.info(f"   -> changed coordinates to {x}/{y}/{z}")

                            # Record the entity at the destination's coordinates
                            self.entities[key].append(entity)

        # Handle repetitions for entities
        if rep:
            copy_entities = copy.deepcopy(self.entities)

            self.entities = defaultdict(list)
            # Loop over all primary copies of the entities
            for key, entities in copy_entities.items():
                for orig_entity in entities:
                    # Save the original entity
                    self.entities[key].append(orig_entity)

                    # Loop over the repetition
                    for repetition in rep:
                        # Make a deepcopy of the entity for each repetition
                        entity = copy.deepcopy(orig_entity)

                        # Calculate the new location of the repeated entity
                        rx, ry, rz = repetition
                        x = entity["x"].value + rx
                        y = entity["y"].value + ry
                        z = entity["z"].value + rz

                        # Get the new key for the new location
                        (
                            region_coord,
                            chunk_coord,
                            _,
                            _,
                        ) = tools.block_to_id_index(x, y, z)
                        key = (region_coord, chunk_coord)

                        # Set the new coordinates for the entity
                        entity["x"].value = x
                        entity["y"].value = y
                        entity["z"].value = z
                        L.info(f"   -> changed repeated coordinates to {x}/{y}/{z}")

                        # Save entity
                        self.entities[key].append(entity)


    def done(self):
        """
        Modify the world with the recorded blocks.
        """
        regions = {}
        # Update the blocks in each affected destination section
        for section_id, updates in self.blocks_map.items():
            region_coord, chunk_coord, ylevel = section_id

            L.info(f"Modifying chunk for region {region_coord} | chunk {chunk_coord}")
            if section_id not in self.write_sections:
                section = self.get_section(section_id)
                self.write_sections[section_id] = section

            for update in updates:
                self.write_sections[section_id].set_block(*update)

            # Store regions that needs to be updated
            if region_coord in regions:
                regions[region_coord].append((chunk_coord, ylevel))
            else:
                regions[region_coord] = [(chunk_coord, ylevel)]

        # Handle all modified regions
        for region_coord, chunk_id in regions.items():
            # Read the region
            region = pyblock.Region(self.path, region_coord)

            # Create the chunk indices
            chunks = {}
            for chunk_coord, ylevel in chunk_id:
                if chunk_coord in chunks:
                    chunks[chunk_coord].append(ylevel)
                else:
                    chunks[chunk_coord] = [ylevel]

            # Handle all modified chunks
            updated_chunks = {}
            for chunk_coord, ylevels in chunks.items():
                key = (region_coord, chunk_coord)
                if key in self.entities:
                    entities_to_update = self.entities[key]
                else:
                    entities_to_update = []
                chunk = region.get_chunk(chunk_coord)

                for ylevel in ylevels:
                    # print(chunk_coord, ylevel)

                    section_id = (region_coord, chunk_coord, ylevel)
                    section = self.write_sections[section_id]
                    chunk.set_section(ylevel, section.get_nbt())

                # Store the manipulated chunk
                updated_chunks[chunk_coord] = chunk.get_bytes(entities_to_update)

            # write the region with the updated chunks
            region.write(updated_chunks)
