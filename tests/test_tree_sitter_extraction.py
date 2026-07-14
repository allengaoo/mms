from mms.analysis.parsers.tree_sitter_parser import TreeSitterParser


def test_java_extracts_ownership_annotations_bases_and_imports() -> None:
    source = """
package com.example;
import java.util.List;
@RestController
class Outer extends Base implements Port {
  @Transactional(readOnly=true)
  public List<String> find(String id) { return null; }
  class Inner { public void run() {} }
}
class Other { public int size() { return 0; } }
"""
    skeleton = TreeSitterParser("java").extract_skeleton(source, "Outer.java")
    classes = {item.name: item for item in skeleton.classes}

    assert skeleton.package == "com.example"
    assert skeleton.imports == ["List"]
    assert classes["Outer"].bases == ["Base", "Port"]
    assert classes["Outer"].annotations == ["RestController"]
    assert [method.name for method in classes["Outer"].methods] == ["find"]
    assert classes["Outer"].methods[0].annotations == [
        "Transactional(readOnly=true)"
    ]
    assert [method.name for method in classes["Outer.Inner"].methods] == ["run"]
    assert [method.name for method in classes["Other"].methods] == ["size"]


def test_go_extracts_receiver_methods_top_level_functions_and_imports() -> None:
    source = """
package order
import "context"
type Repository struct { BaseRepository }
type Port interface { Find(id string) error }
func (r *Repository) Find(ctx context.Context, id string) error { return nil }
func Build(name string) *Repository { return nil }
"""
    skeleton = TreeSitterParser("go").extract_skeleton(source, "order.go")
    classes = {item.name: item for item in skeleton.classes}

    assert skeleton.package == "order"
    assert skeleton.imports == ["context"]
    assert [method.name for method in classes["Repository"].methods] == ["Find"]
    assert [method.name for method in skeleton.top_level_functions] == ["Build"]
    assert "BaseRepository" in classes["Repository"].bases


def test_typescript_extracts_nest_decorators_methods_and_imports() -> None:
    source = """
import { Controller, Get } from '@nestjs/common';
import { UserService } from './service';
@Controller('users')
export class UsersController extends BaseController {
  @Get(':id')
  async findOne(id: string): Promise<string> { return id; }
}
"""
    skeleton = TreeSitterParser("typescript").extract_skeleton(
        source,
        "users.controller.ts",
    )
    controller = skeleton.classes[0]

    assert skeleton.imports == ["Controller", "Get", "UserService"]
    assert controller.name == "UsersController"
    assert controller.annotations == ["Controller('users')"]
    assert controller.bases == ["BaseController"]
    assert controller.methods[0].annotations == ["Get(':id')"]
    assert controller.methods[0].is_async


def test_empty_and_oversized_sources_are_safe() -> None:
    parser = TreeSitterParser("java")
    assert parser.extract_skeleton("", "Empty.java").classes == []
    assert parser.extract_skeleton(" " * (1024 * 1024 + 1), "Large.java").classes == []
