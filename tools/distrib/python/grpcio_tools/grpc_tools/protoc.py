#!/usr/bin/env python

# Copyright 2016 gRPC authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pkg_resources
import sys

# TODO: Figure out how to add this dependency to setuptools.
import six
import os

import contextlib
import importlib
import importlib.machinery
import sys

from grpc_tools import _protoc_compiler

def main(command_arguments):
    """Run the protocol buffer compiler with the given command-line arguments.

  Args:
    command_arguments: a list of strings representing command line arguments to
        `protoc`.
  """
    command_arguments = [argument.encode() for argument in command_arguments]
    return _protoc_compiler.run_main(command_arguments)

def _module_name_to_proto_file(suffix, module_name):
  components = module_name.split(".")
  proto_name = components[-1][:-1*len(suffix)]
  return os.path.sep.join(components[:-1] + [proto_name + ".proto"])

def _proto_file_to_module_name(suffix, proto_file):
  components = proto_file.split(os.path.sep)
  proto_base_name = os.path.splitext(components[-1])[0]
  return os.path.sep.join(components[:-1] + [proto_base_name + suffix])


@contextlib.contextmanager
def _augmented_syspath(new_paths):
  original_sys_path = sys.path
  if new_paths is not None:
    sys.path = sys.path + new_paths
  try:
    yield
  finally:
    sys.path = original_sys_path


# TODO: Investigate making this even more of a no-op in the case that we have
# truly already imported the module.
def get_protos(protobuf_path, include_paths=None):
  with _augmented_syspath(include_paths):
    # TODO: Pull these strings out to module-level constants.
    module_name = _proto_file_to_module_name("_pb2", protobuf_path)
    module = importlib.import_module(module_name)
    return module


def get_services(protobuf_path, include_paths=None):
  get_protos(protobuf_path, include_paths)
  with _augmented_syspath(include_paths):
    module_name = _proto_file_to_module_name("_pb2_grpc", protobuf_path)
    module = importlib.import_module(module_name)
    return module


def get_protos_and_services(protobuf_path, include_paths=None):
  return (get_protos(protobuf_path, include_paths=include_paths),
          get_services(protobuf_path, include_paths=include_paths))



_proto_code_cache = {}

class ProtoLoader(importlib.abc.Loader):
  def __init__(self, suffix, code_fn, module_name, protobuf_path, proto_root):
    self._suffix = suffix
    self._code_fn = code_fn
    self._module_name = module_name
    self._protobuf_path = protobuf_path
    self._proto_root = proto_root

  def create_module(self, spec):
    return None

  def _generated_file_to_module_name(self, filepath):
    components = filepath.split("/")
    return ".".join(components[:-1] + [os.path.splitext(components[-1])[0]])

  def exec_module(self, module):
    assert module.__name__ == self._module_name
    code = None
    if self._module_name in _proto_code_cache:
      code = _proto_code_cache[self._module_name]
      six.exec_(code, module.__dict__)
    else:
      files = self._code_fn(self._protobuf_path.encode('ascii'), [path.encode('ascii') for path in sys.path])
      for f in files[:-1]:
        module_name = self._generated_file_to_module_name(f[0].decode('ascii'))
        if module_name not in sys.modules:
          if module_name not in _proto_code_cache:
            _proto_code_cache[module_name] = f[1]
          importlib.import_module(module_name)
      six.exec_(files[-1][1], module.__dict__)


class ProtoFinder(importlib.abc.MetaPathFinder):
  def __init__(self, suffix, code_fn):
    self._suffix = suffix
    self._code_fn = code_fn

  def find_spec(self, fullname, path, target=None):
    filepath = _module_name_to_proto_file(self._suffix, fullname)
    for search_path in sys.path:
      try:
        prospective_path = os.path.join(search_path, filepath)
        os.stat(prospective_path)
      except FileNotFoundError:
        continue
      else:
        # TODO: Use a stdlib helper function to construct this.
        return importlib.machinery.ModuleSpec(fullname, ProtoLoader(self._suffix, self._code_fn, fullname, filepath, search_path))

sys.meta_path.extend([ProtoFinder("_pb2", _protoc_compiler.get_protos), ProtoFinder("_pb2_grpc", _protoc_compiler.get_services)])

if __name__ == '__main__':
    proto_include = pkg_resources.resource_filename('grpc_tools', '_proto')
    sys.exit(main(sys.argv + ['-I{}'.format(proto_include)]))
