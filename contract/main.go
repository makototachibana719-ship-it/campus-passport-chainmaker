package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"regexp"
	"sort"
	"strconv"

	"chainmaker.org/chainmaker/contract-sdk-go/v2/pb/protogo"
	"chainmaker.org/chainmaker/contract-sdk-go/v2/sandbox"
	"chainmaker.org/chainmaker/contract-sdk-go/v2/sdk"
)

const Limit uint64 = 1000000000000

type Contract struct{}
type fault string

type Task struct {
	ID, Title, Category string
	Reward              uint64
}

type Claim struct {
	ID, TaskID, Owner, Status, Proof string
	Reason, BadgeID, ReviewTx        string
}

type Badge struct {
	ID, Owner, Title, Category string
	Proof, ClaimID, Tx         string
}

type State struct {
	Role, Admin, Issuer, FT, NFT string
	Paused                       bool
	Supply                       uint64
	Balances                     map[string]uint64
	Done                         map[string]bool
	Students                     map[string]bool
	Tasks                        map[string]Task
	Claims                       map[string]Claim
	Badges                       map[string]Badge
}

var (
	idRE   = regexp.MustCompile(`^[A-Za-z0-9_-]{1,40}$`)
	addrRE = regexp.MustCompile(`^[A-Za-z0-9_.-]{1,128}$`)
	hashRE = regexp.MustCompile(`^[0-9a-f]{64}$`)
	numRE  = regexp.MustCompile(`^[0-9]+$`)
)

// 所有业务拒绝和SDK错误在入口统一转成失败响应，不能继续提交状态。
func require(ok bool, message string) {
	if !ok {
		panic(fault(message))
	}
}

func must(err error) {
	if err != nil {
		panic(fault("E_SDK: " + err.Error()))
	}
}

func text(value string, err error) string {
	must(err)
	return value
}

func safe(fn func() interface{}) (r protogo.Response) {
	defer func() {
		if e := recover(); e != nil {
			r = sdk.Error(fmt.Sprint(e))
		}
	}()
	b, err := json.Marshal(fn())
	must(err)
	return sdk.Success(b)
}

func hash(value string) string {
	b := sha256.Sum256([]byte(value))
	return hex.EncodeToString(b[:])
}

func args() map[string]string {
	out := map[string]string{}
	for k, v := range sdk.Instance.GetArgs() {
		out[k] = string(v)
	}
	return out
}

func load() State {
	raw := text(sdk.Instance.GetState("campus", "v1"))
	require(raw != "", "E_INIT: state missing")
	var s State
	must(json.Unmarshal([]byte(raw), &s))
	return s
}

func save(s *State) {
	require(len(s.Tasks) <= 50, "E_LIMIT: max 50 tasks")
	require(len(s.Claims) <= 200, "E_LIMIT: max 200 claims")
	require(len(s.Badges) <= 300, "E_LIMIT: max 300 badges")
	require(len(s.Students) <= 50, "E_LIMIT: max 50 students")
	require(len(s.Done) <= 1000, "E_LIMIT: max 1000 operation IDs")
	b, err := json.Marshal(s)
	must(err)
	require(len(b) <= 512*1024, "E_LIMIT: state too large")
	must(sdk.Instance.PutState("campus", "v1", string(b)))
}

func amount(v string) uint64 {
	require(numRE.MatchString(v), "E_AMOUNT: positive integer required")
	n, err := strconv.ParseUint(v, 10, 64)
	require(err == nil && n > 0 && n <= Limit, "E_AMOUNT: outside range")
	return n
}

func validID(v string) {
	require(v != "" && len(v) <= 128, "E_ID: invalid operation ID")
}

func category(v string) bool {
	return v == "tech" || v == "service" || v == "green"
}

func direct(sender, origin string) {
	require(sender == origin, "E_CALLER: direct user call required")
}

func admin(s *State, sender, origin string) {
	direct(sender, origin)
	require(sender == s.Admin, "E_ROLE: admin required")
}

func cross(name, method string, p map[string]string) []byte {
	a := map[string][]byte{"method": []byte(method)}
	for k, v := range p {
		a[k] = []byte(v)
	}
	r := sdk.Instance.CallContract(name, method, a)
	require(r.Status == sdk.Success(nil).Status,
		"E_CROSS: "+name+"/"+method+": "+r.Message+" "+string(r.Payload))
	return r.Payload
}

func credit(s *State, to string, n uint64) {
	require(addrRE.MatchString(to), "E_ACCOUNT: invalid recipient")
	require(s.Supply <= Limit-n && s.Balances[to] <= Limit-n,
		"E_OVERFLOW: supply or balance limit")
	s.Supply += n
	s.Balances[to] += n
}

func issueBadge(s *State, a map[string]string, tx string) {
	require(!s.Paused, "E_PAUSED: badge issuance paused")
	validID(a["id"])
	require(addrRE.MatchString(a["to"]), "E_ACCOUNT: invalid owner")
	require(len(a["title"]) > 0 && len(a["title"]) <= 240, "E_TITLE")
	require(hashRE.MatchString(a["proof"]), "E_PROOF: SHA256 required")
	_, exists := s.Badges[a["id"]]
	require(!exists, "E_DUPLICATE: badge exists")
	s.Badges[a["id"]] = Badge{
		ID: a["id"], Owner: a["to"], Title: a["title"],
		Category: a["category"], Proof: a["proof"],
		ClaimID: a["claim"], Tx: tx,
	}
}

func (c *Contract) InitContract() protogo.Response {
	return safe(func() interface{} {
		require(text(sdk.Instance.GetState("campus", "v1")) == "", "E_INIT")
		a := args()
		require(a["role"] == "ft" || a["role"] == "nft" || a["role"] == "task",
			"E_ROLE: invalid contract role")
		if a["role"] == "task" {
			require(idRE.MatchString(a["ft"]) && idRE.MatchString(a["nft"]),
				"E_CONFIG: child contract names required")
		}
		s := State{
			Role: a["role"], Admin: text(sdk.Instance.Origin()),
			FT: a["ft"], NFT: a["nft"],
			Balances: map[string]uint64{}, Done: map[string]bool{},
			Students: map[string]bool{}, Tasks: map[string]Task{},
			Claims: map[string]Claim{}, Badges: map[string]Badge{},
		}
		save(&s)
		return map[string]string{"Role": s.Role, "Admin": s.Admin}
	})
}

func (c *Contract) UpgradeContract() protogo.Response {
	return safe(func() interface{} {
		s := load()
		return map[string]string{"Role": s.Role, "Result": "state preserved"}
	})
}

func (c *Contract) InvokeContract(method string) protogo.Response {
	return safe(func() interface{} {
		s := load()
		a := args()
		sender := text(sdk.Instance.Sender())
		origin := text(sdk.Instance.Origin())

		switch method {
		case "WhoAmI":
			return map[string]string{"Sender": sender, "Origin": origin}
		case "Snapshot":
			return s
		case "Info":
			return map[string]interface{}{
				"Role": s.Role, "Admin": s.Admin, "Issuer": s.Issuer,
				"Name": "做的全队校园贡献积分", "Symbol": "POINT",
				"Decimals": 0, "TotalSupply": s.Supply,
			}
		}

		if s.Role == "ft" && method == "BalanceOf" {
			require(addrRE.MatchString(a["account"]), "E_ACCOUNT")
			return s.Balances[a["account"]]
		}
		if s.Role == "nft" {
			switch method {
			case "OwnerOf", "Token":
				b, exists := s.Badges[a["id"]]
				require(exists, "E_NOT_FOUND: badge")
				if method == "OwnerOf" {
					return b.Owner
				}
				return b
			case "BalanceOf":
				count := 0
				for _, b := range s.Badges {
					if b.Owner == a["account"] {
						count++
					}
				}
				return count
			case "Transfer":
				panic(fault("E_SOULBOUND: achievement badges cannot be transferred"))
			}
		}
		if s.Role == "task" && method == "Probe" {
			var identity map[string]string
			must(json.Unmarshal(cross(s.FT, "WhoAmI", map[string]string{}), &identity))
			return identity
		}

		tx := text(sdk.Instance.GetTxId())
		result := interface{}(map[string]string{"Method": method, "Tx": tx})

		if method == "SetIssuer" && (s.Role == "ft" || s.Role == "nft") {
			admin(&s, sender, origin)
			require(addrRE.MatchString(a["issuer"]), "E_ACCOUNT")
			require(s.Issuer == "" || s.Issuer == a["issuer"],
				"E_BOUND: issuer is already fixed")
			s.Issuer = a["issuer"]

		} else if s.Role == "ft" {
			switch method {
			case "Mint", "Award":
				if method == "Mint" {
					admin(&s, sender, origin)
				} else {
					require(s.Issuer != "" && sender == s.Issuer,
						"E_ISSUER: task contract required")
				}
				validID(a["id"])
				key := "mint:" + a["id"]
				require(!s.Done[key], "E_DUPLICATE: reward already issued")
				credit(&s, a["to"], amount(a["amount"]))
				s.Done[key] = true

			case "Transfer":
				direct(sender, origin)
				require(a["from"] == sender, "E_FROM: sender does not own account")
				require(addrRE.MatchString(a["to"]) && a["to"] != sender,
					"E_ACCOUNT: invalid recipient")
				validID(a["id"])
				key := "transfer:" + sender + ":" + a["id"]
				require(!s.Done[key], "E_DUPLICATE: transfer already processed")
				n := amount(a["amount"])
				require(s.Balances[sender] >= n, "E_BALANCE: insufficient balance")
				require(s.Balances[a["to"]] <= Limit-n, "E_OVERFLOW")
				s.Balances[sender] -= n
				s.Balances[a["to"]] += n
				s.Done[key] = true
			default:
				panic(fault("E_METHOD: invalid FT method"))
			}

		} else if s.Role == "nft" {
			switch method {
			case "Mint", "Award":
				if method == "Mint" {
					admin(&s, sender, origin)
				} else {
					require(s.Issuer != "" && sender == s.Issuer && origin == s.Admin,
						"E_ISSUER: administrator-approved task required")
				}
				issueBadge(&s, a, tx)
			case "Pause":
				admin(&s, sender, origin)
				require(a["value"] == "true" || a["value"] == "false", "E_VALUE")
				s.Paused = a["value"] == "true"
			default:
				panic(fault("E_METHOD: invalid NFT method"))
			}

		} else if s.Role == "task" {
			direct(sender, origin)
			switch method {
			case "Register":
				admin(&s, sender, origin)
				require(addrRE.MatchString(a["account"]) && a["account"] != s.Admin,
					"E_ACCOUNT: student required")
				s.Students[a["account"]] = true

			case "Create":
				admin(&s, sender, origin)
				require(idRE.MatchString(a["id"]), "E_ID")
				_, exists := s.Tasks[a["id"]]
				require(!exists, "E_DUPLICATE: task exists")
				require(category(a["category"]), "E_CATEGORY")
				require(len(a["title"]) > 0 && len(a["title"]) <= 240, "E_TITLE")
				n := amount(a["reward"])
				require(n <= 10000, "E_AMOUNT: task reward max 10000")
				s.Tasks[a["id"]] = Task{
					ID: a["id"], Title: a["title"], Category: a["category"], Reward: n,
				}

			case "Claim":
				require(s.Students[sender], "E_STUDENT: registered student required")
				_, exists := s.Tasks[a["task"]]
				require(exists, "E_NOT_FOUND: task")
				id := hash(a["task"] + "|" + sender)
				_, exists = s.Claims[id]
				require(!exists, "E_DUPLICATE: task already claimed")
				s.Claims[id] = Claim{
					ID: id, TaskID: a["task"], Owner: sender, Status: "CLAIMED",
				}
				result = map[string]string{"ClaimID": id, "Tx": tx}

			case "Submit":
				cl, exists := s.Claims[a["claim"]]
				require(exists && cl.Owner == sender, "E_OWNER: claim owner required")
				require(cl.Status == "CLAIMED" || cl.Status == "REJECTED",
					"E_STATE: cannot submit now")
				require(hashRE.MatchString(a["proof"]), "E_PROOF: SHA256 required")
				cl.Proof, cl.Status, cl.Reason = a["proof"], "SUBMITTED", ""
				s.Claims[cl.ID] = cl

			case "Review":
				admin(&s, sender, origin)
				cl, exists := s.Claims[a["claim"]]
				require(exists && cl.Status == "SUBMITTED",
					"E_STATE: submitted claim required")
				require(a["approve"] == "true" || a["approve"] == "false", "E_VALUE")
				require(len(a["reason"]) <= 240, "E_REASON")
				cl.Reason, cl.ReviewTx = a["reason"], tx
				if a["approve"] == "false" {
					require(a["reason"] != "", "E_REASON: rejection reason required")
					cl.Status = "REJECTED"
				} else {
					t := s.Tasks[cl.TaskID]
					// 同一笔审核交易依次调用积分和徽章合约。
					// 任一子调用失败，向上返回失败，不保存已完成状态。
					cross(s.FT, "Award", map[string]string{
						"id": cl.ID, "to": cl.Owner,
						"amount": strconv.FormatUint(t.Reward, 10),
					})
					cross(s.NFT, "Award", map[string]string{
						"id": cl.ID, "to": cl.Owner, "title": t.Title,
						"category": t.Category, "proof": cl.Proof, "claim": cl.ID,
					})
					cl.Status, cl.BadgeID = "APPROVED", cl.ID
				}
				s.Claims[cl.ID] = cl
				result = cl

			case "Milestone":
				require(s.Students[sender], "E_STUDENT")
				key := "milestone:" + sender
				require(!s.Done[key], "E_DUPLICATE: milestone already rewarded")
				categories := map[string]bool{}
				ids := []string{}
				for _, cl := range s.Claims {
					if cl.Owner == sender && cl.Status == "APPROVED" {
						categories[s.Tasks[cl.TaskID].Category] = true
						ids = append(ids, cl.ID)
					}
				}
				require(categories["tech"] && categories["service"] && categories["green"],
					"E_CONDITION: complete all three categories")
				sort.Strings(ids)
				cross(s.FT, "Award", map[string]string{
					"id": "milestone-" + hash(sender), "to": sender, "amount": "30",
				})
				s.Done[key] = true
				result = map[string]interface{}{
					"Bonus": 30, "EvidenceClaims": ids, "Tx": tx,
				}
			default:
				panic(fault("E_METHOD: invalid task method"))
			}
		} else {
			panic(fault("E_METHOD"))
		}

		save(&s)
		sdk.Instance.EmitEvent("Campus", []string{s.Role, method, tx})
		return result
	})
}

func main() {
	if err := sandbox.Start(new(Contract)); err != nil {
		log.Fatal(err)
	}
}
