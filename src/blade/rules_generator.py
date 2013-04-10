"""

 Copyright (c) 2011 Tencent Inc.
 All rights reserved.

 Author: Huan Yu <huanyu@tencent.com>
         Feng Chen <phongchen@tencent.com>
         Yi Wang <yiwang@tencent.com>
         Chong Peng <michaelpeng@tencent.com>
 Date:   October 20, 2011

 This is the scons rules genearator module which invokes all
 the builder objects or scons objects to generate scons rules.

"""


import os
import socket
import subprocess
import string
import time
import blade_util
import configparse
from blade_platform import CcFlagsManager
from blade_platform import SconsPlatform
from blade_util import info
from blade_util import var_to_list
from blade_util import warning


class SconsRules(object):
    """The super scons rules class that generates scons rules.

    This class is different from the scons target class,  the former is to used
    to generate the basic rules or functions, the latter one is to used to
    generate the scons target rules, like cc object, java jar.

    """
    def __init__(self, options, build_dir, gcc_version,
                 python_inc, build_environment):
        """Init method. """
        self.rules_buf = []
        self.options = options
        self.build_dir = build_dir
        self.gcc_version = gcc_version
        self.python_inc = python_inc
        self.build_environment = build_environment
        self.ccflags_manager = CcFlagsManager(options)
        self.env_list = ['env', 'env_with_error', 'env_no_warning']

    def _add_rule(self, rule):
        """Append one rule to buffer. """
        self.rules_buf.append('%s\n' % rule)

    def get_rules(self):
        """Return rules buffer. """
        return self.rules_buf

class SconsRulesHelper(SconsRules):
    """One subclass of SconsRules. """
    def __init__(self, options, build_dir, gcc_version,
                 python_inc, build_environment, svn_roots=[]):
        """Init method. """
        SconsRules.__init__(self, options, build_dir,
                            gcc_version, python_inc, build_environment)
        self.svn_roots = svn_roots
        self.svn_info_map = {}

        self.version_cpp_compile_template = string.Template("""
env_version = Environment(ENV = os.environ)
env_version.Append(SHCXXCOMSTR = '$updateinfo')
env_version.Append(CPPFLAGS = '-m$m')
version_obj = env_version.SharedObject('$filename')
""")
        self.blade_config = configparse.blade_config
        self.distcc_enabled = self.blade_config.get_config(
                              'distcc_config').get('enabled', False)
        self.dccc_enabled = self.blade_config.get_config(
                              'link_config').get('enable_dccc', False)

    def _append_prefix_to_building_var(
                self,
                prefix="",
                building_var="",
                condition=False):
        """A helper method: append prefix to building var if condition is True."""
        return "%s %s" % (prefix, building_var) if condition else building_var

    def _get_version_info(self):
        """Gets svn root dir info. """
        for root_dir in self.svn_roots:
            lc_all_env = os.environ
            lc_all_env['LC_ALL'] = 'POSIX'
            root_dir_realpath =  os.path.realpath(root_dir)
            svn_working_dir = os.path.dirname(root_dir_realpath)
            svn_dir = os.path.basename(root_dir_realpath)

            if not os.path.exists("%s/.svn" % root_dir):
                warning("%s is not under version control" % root_dir)
                continue

            p = subprocess.Popen("svn info %s" % svn_dir,
                                 env=lc_all_env,
                                 cwd="%s" % svn_working_dir,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 shell=True)
            std_out, std_err = p.communicate()
            if p.returncode:
                warning("failed to get version control info in %s" % root_dir)
            else:
                self.svn_info_map[root_dir] = std_out.replace("\n", "\\n\\\n")

    def generate_version_file(self):
        """Generate version information files. """
        self._get_version_info()
        svn_info_len = len(self.svn_info_map.keys())

        if not os.path.exists(self.build_dir):
            os.mkdir(self.build_dir)
        version_cpp = open("%s/version.cpp" % self.build_dir, "w")

        print >>version_cpp, "/* This file was generated by blade */"
        print >>version_cpp, 'extern "C" {'
        print >>version_cpp, 'namespace binary_version {'
        print >>version_cpp, 'extern const int kSvnInfoCount = %d;' % svn_info_len

        svn_info_array = "{"
        for idx in range(svn_info_len):
            key_with_idx = self.svn_info_map.keys()[idx]
            svn_info_line = '"%s"' % self.svn_info_map[key_with_idx]
            svn_info_array += svn_info_line
            if idx != (svn_info_len - 1):
                svn_info_array += ","
        svn_info_array += "}"

        print >>version_cpp, 'extern const char* const kSvnInfo[%d] = %s;' % (
                svn_info_len, svn_info_array)
        print >>version_cpp, 'extern const char kBuildType[] = "%s";' % self.options.profile
        print >>version_cpp, 'extern const char kBuildTime[] = "%s";' % time.asctime()
        print >>version_cpp, 'extern const char kBuilderName[] = "%s";' % os.getenv('USER')
        print >>version_cpp, (
        'extern const char kHostName[] = "%s";' % socket.gethostname())
        compiler = 'GCC %s' % self.gcc_version
        print >>version_cpp, 'extern const char kCompiler[] = "%s";' % compiler
        print >>version_cpp, '}}'

        version_cpp.close()

        self._add_rule("VariantDir('%s', '.', duplicate=0)" % self.build_dir)
        self._add_rule(self.version_cpp_compile_template.substitute(
            updateinfo = "version information updated",
            m = self.options.m,
            filename = "%s/version.cpp" % self.build_dir))

    def generate_imports_functions(self, blade_path):
        """Generates imports and functions. """
        self._add_rule(
            r"""
import sys
sys.path.insert(0, '%s')
""" % blade_path)
        self._add_rule(
            r"""
import os
import subprocess
import signal
import time
import socket
import glob
import blade_util
from build_environment import ScacheManager
import scons_helper
from scons_helper import create_fast_link_builders
from scons_helper import echospawn
from scons_helper import error_colorize
from scons_helper import generate_python_binary
from scons_helper import generate_resource_file
from scons_helper import generate_resource_header
from scons_helper import MakeAction
""")

        if hasattr(self.options, 'verbose') and self.options.verbose:
            self._add_rule("scons_helper.option_verbose = True")

        self._add_rule((
                """if not os.path.exists('%s'):
    os.mkdir('%s')""") % (self.build_dir, self.build_dir))

    def generate_top_level_env(self):
        """generates top level environment. """
        self._add_rule("os.environ['LC_ALL'] = 'C'")
        self._add_rule("top_env = Environment(ENV=os.environ)")

    def generate_compliation_verbose(self):
        """Generates color and verbose message. """
        self._add_rule("top_env.Decider('MD5-timestamp')")
        self._add_rule("colors = scons_helper.colors")
        color_enabled = "True" if blade_util.color_enabled else "False"
        self._add_rule("blade_util.color_enabled=%s" % color_enabled)

        if hasattr(self.options, 'color') and not self.options.color:
            self._add_rule(
                """
for key, value in colors.iteritems():
    colors[key] = ''
""")
        if hasattr(self.options, 'verbose') and not self.options.verbose:
            self._add_rule("top_env['SPAWN'] = echospawn")

        self._add_rule(
                """
compile_proto_cc_message = '%sCompiling %s$SOURCE%s to cc source%s' % \
    (colors['cyan'], colors['purple'], colors['cyan'], colors['end'])

compile_proto_java_message = '%sCompiling %s$SOURCE%s to java source%s' % \
    (colors['cyan'], colors['purple'], colors['cyan'], colors['end'])

compile_proto_php_message = '%sCompiling %s$SOURCE%s to php source%s' % \
    (colors['cyan'], colors['purple'], colors['cyan'], colors['end'])

compile_proto_python_message = '%sCompiling %s$SOURCE%s to python source%s' % \
    (colors['cyan'], colors['purple'], colors['cyan'], colors['end'])

compile_resource_header_message = '%sGenerating resource header %s$TARGET%s%s' % \
    (colors['cyan'], colors['purple'], colors['cyan'], colors['end'])

compile_resource_message = '%sCompiling %s$SOURCE%s as resource file%s' % \
    (colors['cyan'], colors['purple'], colors['cyan'], colors['end'])

compile_source_message = '%sCompiling %s$SOURCE%s%s' % \
    (colors['cyan'], colors['purple'], colors['cyan'], colors['end'])

link_program_message = '%sLinking Program %s$TARGET%s%s' % \
    (colors['green'], colors['purple'], colors['green'], colors['end'])

link_library_message = '%sCreating Static Library %s$TARGET%s%s' % \
    (colors['green'], colors['purple'], colors['green'], colors['end'])

ranlib_library_message = '%sRanlib Library %s$TARGET%s%s' % \
    (colors['green'], colors['purple'], colors['green'], colors['end']) \

link_shared_library_message = '%sLinking Shared Library %s$TARGET%s%s' % \
    (colors['green'], colors['purple'], colors['green'], colors['end'])

compile_java_jar_message = '%sGenerating java jar %s$TARGET%s%s' % \
    (colors['cyan'], colors['purple'], colors['cyan'], colors['end'])

compile_python_binary_message = '%sGenerating python binary %s$TARGET%s%s' % \
    (colors['cyan'], colors['purple'], colors['cyan'], colors['end'])

compile_yacc_message = '%sYacc %s$SOURCE%s to $TARGET%s' % \
    (colors['cyan'], colors['purple'], colors['cyan'], colors['end'])

compile_swig_python_message = '%sCompiling %s$SOURCE%s to python source%s' % \
    (colors['cyan'], colors['purple'], colors['cyan'], colors['end'])

compile_swig_java_message = '%sCompiling %s$SOURCE%s to java source%s' % \
    (colors['cyan'], colors['purple'], colors['cyan'], colors['end'])

compile_swig_php_message = '%sCompiling %s$SOURCE%s to php source%s' % \
    (colors['cyan'], colors['purple'], colors['cyan'], colors['end'])
""")

        if hasattr(self.options, 'verbose') and not self.options.verbose:
            self._add_rule(
            r"""
top_env.Append(
  CXXCOMSTR = compile_source_message,
  CCCOMSTR = compile_source_message,
  SHCCCOMSTR = compile_source_message,
  SHCXXCOMSTR = compile_source_message,
  ARCOMSTR = link_library_message,
  RANLIBCOMSTR = ranlib_library_message,
  SHLINKCOMSTR = link_shared_library_message,
  LINKCOMSTR = link_program_message,
  JAVACCOMSTR = compile_source_message
)""")

    def _generate_fast_link_builders(self):
        """Generates fast link builders if it is specified in blade bash. """
        link_config = configparse.blade_config.get_config('link_config')
        enable_dccc = link_config['enable_dccc']
        if link_config['link_on_tmp']:
            if (not enable_dccc) or (
                    enable_dccc and not self.build_environment.dccc_env_prepared):
                self._add_rule("create_fast_link_builders(top_env)")

    def generate_builders(self):
        """Generates common builders. """
        # Generates builders specified in blade bash at first
        self._generate_fast_link_builders()

        protoc_config = configparse.blade_config.get_config('protoc_config')
        protoc_bin = protoc_config['protoc']
        protobuf_path = protoc_config['protobuf_path']

        protobuf_include_path = protoc_config['protobuf_include_path']
        protobuf_path_list = []
        for p in protobuf_include_path.split(" "):
            p = p.strip()
            protobuf_path_list.append("-I%s" % p)

        protobuf_include_path_str = ' '.join(protobuf_path_list)

        protobuf_php_path = protoc_config['protobuf_php_path']
        protoc_php_plugin = protoc_config['protoc_php_plugin']
        # Genreates common builders now
        builder_list = []
        self._add_rule("time_value = Value('%s')" %  time.asctime())
        self._add_rule(
            "proto_bld = Builder(action = MakeAction('%s "
            "--proto_path=. -I. %s -I=`dirname $SOURCE` "
            "--cpp_out=%s "
            "$SOURCE', compile_proto_cc_message))" % (
                    protoc_bin, protobuf_include_path_str, self.build_dir))
        builder_list.append("BUILDERS = {'Proto' : proto_bld}")

        self._add_rule(
            "proto_java_bld = Builder(action = MakeAction('%s --proto_path=. "
            "--proto_path=%s --java_out=%s/`dirname $SOURCE` "
            "$SOURCE', compile_proto_java_message))" % (
                    protoc_bin, protobuf_path, self.build_dir))
        builder_list.append("BUILDERS = {'ProtoJava' : proto_java_bld}")

        self._add_rule(
            "proto_php_bld = Builder(action = MakeAction('%s "
            "--proto_path=. "
            "--plugin=protoc-gen-php=%s "
            "-I. %s -I%s -I=`dirname $SOURCE` "
            "--php_out=%s/`dirname $SOURCE` "
            "$SOURCE', compile_proto_php_message))" % (
                    protoc_bin, protoc_php_plugin, protobuf_include_path_str,
                    protobuf_php_path, self.build_dir))
        builder_list.append("BUILDERS = {'ProtoPhp' : proto_php_bld}")

        self._add_rule(
            "proto_python_bld = Builder(action = MakeAction('%s "
            "--proto_path=. "
            "-I. %s -I=`dirname $SOURCE` "
            "--python_out=%s "
            "$SOURCE', compile_proto_python_message))" % (
                    protoc_bin, protobuf_include_path_str, self.build_dir))
        builder_list.append("BUILDERS = {'ProtoPython' : proto_python_bld}")

        self._add_rule(
                     r"""
blade_jar_bld = Builder(action = MakeAction('jar cf $TARGET -C `dirname $SOURCE` .',
    compile_java_jar_message))

yacc_bld = Builder(action = MakeAction('bison $YACCFLAGS -d -o $TARGET $SOURCE',
    compile_yacc_message))

resource_header_bld = Builder(action = MakeAction(generate_resource_header,
    compile_resource_header_message))

resource_file_bld = Builder(action = MakeAction(generate_resource_file,
    compile_resource_message))

python_binary_bld = Builder(action = MakeAction(generate_python_binary,
    compile_python_binary_message))
""")
        builder_list.append("BUILDERS = {'BladeJar' : blade_jar_bld}")
        builder_list.append("BUILDERS = {'Yacc' : yacc_bld}")
        builder_list.append("BUILDERS = {'ResourceHeader' : resource_header_bld}")
        builder_list.append("BUILDERS = {'ResourceFile' : resource_file_bld}")
        builder_list.append("BUILDERS = {'PythonBinary' : python_binary_bld}")

        for builder in builder_list:
            self._add_rule("top_env.Append(%s)" % builder)

    def generate_compliation_flags(self):
        """Generates compliation flags. """
        toolchain_dir = os.environ.get('TOOLCHAIN_DIR', '')
        if toolchain_dir and not toolchain_dir.endswith('/'):
            toolchain_dir += '/'
        cpp_str = toolchain_dir + os.environ.get('CPP', 'cpp')
        cc_str = toolchain_dir + os.environ.get('CC', 'gcc')
        cxx_str = toolchain_dir + os.environ.get('CXX', 'g++')
        ld_str = toolchain_dir + os.environ.get('LD', 'g++')
        info("CPP=%s" % cpp_str)
        info("CC=%s" % cc_str)
        info("CXX=%s" % cxx_str)
        info("LD=%s" % ld_str)

        self.ccflags_manager.set_cpp_str(cpp_str)

        (warn_cppflags, warn_cxxflags) = self.ccflags_manager.get_warning_ccflags()
        (err_cflags,
         err_cppflags,
         err_cxxflags) = self.ccflags_manager.get_error_ccflags()

        (cppflags_except_warning,
         linkflags) = self.ccflags_manager.get_flags_except_warning()

        # To modify CC, CXX, LD according to the building environment and
        # project configuration
        build_with_distcc = (self.distcc_enabled and
                             self.build_environment.distcc_env_prepared)
        cc_str = self._append_prefix_to_building_var(
                         prefix="distcc",
                         building_var=cc_str,
                         condition=build_with_distcc)

        cxx_str = self._append_prefix_to_building_var(
                         prefix="distcc",
                         building_var=cxx_str,
                         condition=build_with_distcc)

        build_with_ccache = self.build_environment.ccache_installed
        cc_str = self._append_prefix_to_building_var(
                         prefix="ccache",
                         building_var=cc_str,
                         condition=build_with_ccache)

        cxx_str = self._append_prefix_to_building_var(
                         prefix="ccache",
                         building_var=cxx_str,
                         condition=build_with_ccache)

        build_with_dccc = (self.dccc_enabled and
                           self.build_environment.dccc_env_prepared)
        ld_str = self._append_prefix_to_building_var(
                        prefix="dccc",
                        building_var=ld_str,
                        condition=build_with_dccc)

        cc_env_str = "CC='%s', CXX='%s'" % (cc_str, cxx_str)
        ld_env_str = "LINK='%s'" % ld_str

        cc_config = configparse.blade_config.get_config('cc_config')
        extra_incs = cc_config['extra_incs']
        include_list = []
        for inc in extra_incs.split(" "):
            include_list.append("'%s'" % inc)
        extra_includes = ", ".join(include_list)

        for env in self.env_list:
            self._add_rule("%s = top_env.Clone()" % env)

        self._add_rule("""
%s.Replace(%s,
          CPPPATH=[%s, '%s', '%s'],
          CPPFLAGS=%s,
          CFLAGS=%s,
          CXXFLAGS=%s,
          %s,
          LINKFLAGS=%s)
""" % (self.env_list[0], cc_env_str,
       extra_includes, self.build_dir, self.python_inc,
       cc_config['cppflags'] + warn_cppflags + cppflags_except_warning,
       cc_config['cflags'],
       cc_config['cxxflags'] + warn_cxxflags,
       ld_env_str,
       linkflags))

        self._add_rule("""
%s.Replace(%s,
          CPPPATH=[%s, '%s', '%s'],
          CPPFLAGS=%s,
          CFLAGS=%s,
          CXXFLAGS=%s,
          %s,
          LINKFLAGS=%s)
""" % (self.env_list[1], cc_env_str,
       extra_includes,
       self.build_dir, self.python_inc,
       cc_config['cppflags'] + warn_cppflags  + err_cppflags + cppflags_except_warning,
       cc_config['cflags'] + err_cflags,
       cc_config['cxxflags'] + warn_cxxflags + err_cxxflags,
       ld_env_str,
       linkflags))

        self._add_rule("""
%s.Replace(%s,
          CPPPATH=[%s, '%s', '%s'],
          CPPFLAGS=%s,
          CFLAGS=%s,
          CXXFLAGS=%s,
          %s,
          LINKFLAGS=%s)
""" % (self.env_list[2], cc_env_str,
       extra_includes, self.build_dir, self.python_inc,
       cc_config['cppflags'] + cppflags_except_warning,
       cc_config['cflags'],
       cc_config['cxxflags'],
       ld_env_str,
       linkflags))

        if hasattr(self.options, 'cache_dir') and self.options.cache_dir:
            if not self.build_environment.ccache_installed:
                self._add_rule("CacheDir('%s')" % self.options.cache_dir)
                self._add_rule("blade_util.info('using cache directory %s')" % (
                        self.options.cache_dir))
                if hasattr(self.options, 'cache_size') and (
                        self.options.cache_size != -1):
                    self._add_rule("scache_manager = ScacheManager('%s', cache_limit=%s)" % (
                            self.options.cache_dir, self.options.cache_size))
                    self._add_rule("Progress(scache_manager, interval=100)")
                    self._add_rule("blade_util.info('scache size %d')" % (
                                   self.options.cache_size))

        if not self.build_environment.ccache_installed:
            if hasattr(self.options, 'cache_dir') and (
                        not self.options.cache_dir):
                default_cache_dir = os.path.expanduser("~/.bladescache")
                default_cache_size = 1024*1024*1024
                warning("there is no ccache and you don't have scache enabled, "
                        "use %s as current scache dir, scache size 1G" % (
                        default_cache_dir))
                self._add_rule("CacheDir('%s')" % default_cache_dir)
                self._add_rule("blade_util.info('using cache directory %s')" % (
                               default_cache_dir))
                self._add_rule("scache_manager = ScacheManager('%s', "
                               "cache_limit=%d)" % (
                            default_cache_dir, default_cache_size))
                self._add_rule("Progress(scache_manager, interval=100)")

        if build_with_ccache:
            self.build_environment.setup_ccache_env(self.env_list)

        if build_with_distcc:
            self.build_environment.setup_distcc_env(self.env_list)

        for rule in self.build_environment.get_rules():
            self._add_rule(rule)

    def generate_all(self, blade_path):
        """Generates all rules. """
        self.generate_imports_functions(blade_path)
        self.generate_version_file()
        self.generate_top_level_env()
        self.generate_compliation_verbose()
        self.generate_builders()
        self.generate_compliation_flags()


class SconsRulesGenerator(object):
    """The main class to generate scons rules and outputs rules to SConstruct. """
    def __init__(self, scons_path, blade_path, blade):
        """Init method. """
        self.blade_path = blade_path
        self.blade = blade
        self.targets = self.blade.get_all_targets_expanded()
        self.scons_platform = self.blade.get_scons_platform()
        self.rules_buf = []
        self.scons_path = scons_path

        build_dir = self.blade.get_build_path()
        options = self.blade.get_options()
        gcc_version = self.scons_platform.get_gcc_version()
        python_inc = self.scons_platform.get_python_include()

        self.scons_rules_helper = SconsRulesHelper(options,
                                                   build_dir,
                                                   gcc_version,
                                                   python_inc,
                                                   self.blade.build_environment,
                                                   self.blade.svn_root_dirs)
        try:
            os.remove("blade-bin")
        except os.error:
            pass
        os.symlink(os.path.abspath(build_dir), "blade-bin")

    def generate_scons_script(self):
        """Generates SConstruct script. """
        # Generate headers for SConstruct
        self.scons_rules_helper.generate_all(self.blade_path)

        self.rules_buf += self.scons_rules_helper.get_rules()

        # Generate scons rules for each target
        self.rules_buf += self.blade.get_targets_rules()

        # Write to SConstruct
        self.scons_file_fd = open(self.scons_path, 'w')
        self.scons_file_fd.writelines(self.rules_buf)
        self.scons_file_fd.close()
        return self.rules_buf